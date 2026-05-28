# -- coding: utf-8 --
"""
Batch scrape Instagram posts (oldest -> newest) for:
- Dim_Posts (one row per post)
- Fact_Comments (all comments per post)
- Fact_Likers (likers per post; bounded in 'fast' mode)

Features:
- Appends to CSVs after EACH post (crash-safe).
- Resumes automatically using processed_shortcodes.txt.
- --reset-daily: clears yesterday's processed file to start fresh each new day.
- Uses GraphQL for first-page comments (if SESSIONID provided), falls back to Selenium when needed.
- Headless Chrome supported.
"""

import os
import time
import csv
import json
import argparse
from datetime import datetime, date, timezone
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote

from dotenv import load_dotenv

# ---------- Optional GraphQL ----------
try:
    import httpx
except Exception:
    httpx = None

# ---------- Selenium ----------
from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ---------- Environment ----------
load_dotenv()
IG_SESSIONID = (os.getenv("SESSIONID") or "").strip()
IG_APP_ID = "936619743392459"
DOC_ID_POST = "8845758582119845"

CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", r"C:\Users\Erez\SeleniumProfile")
CHROME_PROFILE_DIR   = os.getenv("CHROME_PROFILE_DIR", "Default")

# ---------- Output location ----------
BASE_OUT_DIR = r"C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media"

from datetime import date
RUN_TAG = "2026-03-03"

RUN_DIR = os.path.join(BASE_OUT_DIR, RUN_TAG)
os.makedirs(RUN_DIR, exist_ok=True)

CSV_POSTS      = os.path.join(RUN_DIR, "batch_posts.csv")
CSV_COMMENTS   = os.path.join(RUN_DIR, "batch_comments.csv")
CSV_LIKERS     = os.path.join(RUN_DIR, "batch_likers.csv")
PROCESSED_FILE = os.path.join(RUN_DIR, "processed_shortcodes.txt")
# ---------- CSV helpers ----------
def append_csv(path: str, rows: List[Dict], headers: List[str]) -> None:
    if not rows:
        return
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            w.writeheader()
        w.writerows(rows)

def load_processed() -> set:
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return {x.strip() for x in f if x.strip()}
    except FileNotFoundError:
        return set()

def mark_processed(shortcode: str) -> None:
    with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
        f.write(shortcode + "\n")

def reset_processed_if_stale(reset_daily: bool) -> None:
    if not reset_daily or not os.path.exists(PROCESSED_FILE):
        return
    mtime = datetime.fromtimestamp(os.path.getmtime(PROCESSED_FILE)).date()
    if mtime < date.today():
        try:
            os.remove(PROCESSED_FILE)
        except Exception:
            pass

# ---------- CLI ----------
parser = argparse.ArgumentParser("comments_single_only")
parser.add_argument("--profile", required=True, help="Instagram profile username to scan")
parser.add_argument("--limit", type=int, default=None, help="Number of posts to process (oldest -> newest)")
parser.add_argument("--headless", action="store_true", help="Use headless Chrome")
parser.add_argument("--likes-mode", choices=["off","fast","deep"], default="fast",
                    help="Likers scraping: off=skip, fast=bounds by time/users, deep=try harder/longer")
parser.add_argument("--max-likers", type=int, default=1200, help="Max likers per post in fast/deep")
parser.add_argument("--max-seconds-likers", type=int, default=180, help="Max seconds per post in fast/deep")
parser.add_argument("--comments", choices=["auto","off","force"], default="auto",
                    help="Comments scraping with Selenium: auto=if more pages or GraphQL fails/returns none, off=skip, force=always")
parser.add_argument("--pause-every", type=int, default=0, help="Pause after N posts (0=disable)")
parser.add_argument("--pause-seconds", type=int, default=0, help="Pause length in seconds when pause-every > 0")
parser.add_argument("--reset-daily", action="store_true",
                    help="If processed_shortcodes.txt is from a previous day, delete it at start")
args = parser.parse_args()

# ---------- Date normalization ----------
def to_date_str(val) -> str:
    """Return YYYY-MM-DD from epoch seconds/ms or ISO-like strings. Empty string on failure."""
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if s.isdigit():
        n = int(s)
        if n > 10_000_000_000:  # milliseconds → seconds
            n //= 1000
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
        except Exception:
            return ""
    # ISO text (possibly with 'Z')
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt.date().isoformat()
    except Exception:
        # last resort: slice YYYY-MM-DD if present
        return s[:10] if len(s) >= 10 else ""

# ---------- Helpers ----------
def parse_shortcode(url_or_shortcode: str) -> str:
    s = url_or_shortcode.strip()
    if "instagram.com" in s:
        for part in ("/p/", "/reel/"):
            if part in s:
                return s.split(part, 1)[1].split("/", 1)[0]
    return s.split("?")[0].split("#")[0]

def make_client() -> Optional["httpx.Client"]:
    if not httpx or not IG_SESSIONID:
        return None
    return httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
            "Accept": "/",
            "Accept-Language": "en-US,en;q=0.9",
            "x-ig-app-id": IG_APP_ID,
        },
        cookies={"sessionid": IG_SESSIONID},
        timeout=httpx.Timeout(25.0)
    )

def graphql_post(post_url: str, shortcode: str, client: "httpx.Client") -> dict:
    """Call Instagram GraphQL for a post/reel. If referer mismatch, auto-try the alternate path."""
    def _try(pre_url: str) -> dict:
        pre = client.get(pre_url, follow_redirects=False)
        pre.raise_for_status()
        csrf = client.cookies.get("csrftoken", "") or "missing"
        variables = quote(json.dumps({
            "shortcode": shortcode,
            "fetch_tagged_user_count": None,
            "hoisted_comment_id": None,
            "hoisted_reply_id": None
        }, separators=(',', ':')))
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "x-csrftoken": csrf,
            "x-ig-app-id": IG_APP_ID,
            "x-requested-with": "XMLHttpRequest",
            "referer": pre_url,
            "origin": "https://www.instagram.com",
        }
        r = client.post("https://www.instagram.com/graphql/query",
                        data=f"variables={variables}&doc_id={DOC_ID_POST}",
                        headers=headers)
        r.raise_for_status()
        return r.json()["data"]["xdt_shortcode_media"]

    try:
        return _try(post_url)
    except Exception as e1:
        alt = post_url.replace("/reel/", "/p/") if "/reel/" in post_url else post_url.replace("/p/", "/reel/")
        try:
            return _try(alt)
        except Exception:
            raise e1

# ---------- Selenium setup ----------
def selenium_setup(headless: bool) -> Tuple[webdriver.Chrome, WebDriverWait]:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={CHROME_PROFILE_DIR}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument("--disable-features=AutomationControlled")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    
    # --- תוספות ליציבות וביצועים ---
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer") # חדש: מונע שימוש גרפי כבד
    opts.add_argument("--disable-dev-shm-usage")     # חדש: מונע קריסת זיכרון
    opts.add_argument("--log-level=3")                 # חדש: משתיק רעש בלוגים
    # -------------------------------
    
    opts.add_argument("--no-sandbox")
    opts.add_argument("--enable-unsafe-swiftshader")
    opts.page_load_strategy = "eager"

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.set_page_load_timeout(120)
    driver.set_script_timeout(900)
    wait = WebDriverWait(driver, 25)
    return driver, wait

def safe_get(driver: webdriver.Chrome, url: str, retries: int = 3, base_sleep: float = 3.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            return True
        except (WebDriverException, TimeoutException) as e:
            print(f"⚠ safe_get attempt {attempt}/{retries} failed: {e}")
            if attempt == retries:
                return False
            try: driver.execute_script("window.stop();")
            except Exception: pass
            time.sleep(base_sleep * attempt)
            try: driver.get("about:blank")
            except Exception: pass
            time.sleep(0.5)
    return False

# ---------- JS payloads ----------
JS_COMMENTS = r"""
var done = arguments[arguments.length - 1];
(async function(){
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const txt=el=>(el&&el.textContent||"").trim();
  const qsa=(root,sel)=>Array.prototype.slice.call((root||document).querySelectorAll(sel)||[]);
  async function expand(maxClicks){
    maxClicks=maxClicks||150;
    for(let i=0;i<maxClicks;i++){
      let clicked=false;
      const btns=qsa(document,"button,div[role='button']")
        .filter(b=>/View all|View more|Load more|See more|show more/i.test(txt(b)));
      for(const b of btns){ if(b.offsetParent){ try{b.scrollIntoView({block:'center'})}catch(e){} try{b.click()}catch(e){} clicked=true; await sleep(500); break; } }
      if(!clicked) break;
    }
  }
  function clean(s){ return (s||"").replace(/[\u200f\u200e\u2066-\u2069]/g," ").replace(/\s+/g," ").trim(); }
  function userFromHref(h){ const m=(h||"").match(/^\/([^\/?#]+)\/$/); return m?m[1]:null; }

  await expand(150);
  const out=[];
  qsa(document,"ul li").forEach(li=>{
    const a=li.querySelector("a[href^='/'][role='link']"); if(!a) return;
    const u=userFromHref(a.getAttribute("href")); if(!u) return;
    const langEl=li.querySelector("[lang]");
    const raw=langEl?txt(langEl):qsa(li,"span").map(e=>txt(e)).filter(Boolean).join(" ");
    const c=clean(raw); if(!c) return;
    let ts=""; const t=li.querySelector("time"); if(t){ ts=t.getAttribute("datetime")||txt(t); }
    out.push({username:u, comment:c, posted_at:ts, media_url:location.href});
  });
  const seen=new Set(), res=[];
  out.forEach(r=>{ const k=r.username+"||"+r.comment; if(!seen.has(k)){ seen.add(k); res.push(r);} });
  done({ok:true, comments:res});
})().catch(e=>done({ok:false, error:String(e&&(e.stack||e.message||e))}));
"""

JS_LIKERS = r"""
var done = arguments[arguments.length - 1];
(async function(){
  const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));
  const qsa   = (root, sel)=>Array.prototype.slice.call((root||document).querySelectorAll(sel)||[]);
  const cfg = (function(){ try{ return window.LIKES_CFG || {}; }catch(e){ return {}; } })();
  const MAX_SECONDS = cfg.maxSeconds || 180;
  const MAX_USERS   = cfg.maxUsers   || 1200;

  function visible(el){ if(!el) return false; const r=el.getBoundingClientRect(); return r.width>0 && r.height>0; }
  function clickHard(el){ try{ el.scrollIntoView({block:"center"});}catch(e){} try{ el.click(); }catch(e){} try{ el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true})); }catch(e){} }
  function pickAnyDialog(){ return document.querySelector('div[role="dialog"]'); }
  function isPostDialog(d){ return !!(d && d.querySelector('article')); }
  function pickLikesDialog(){
    const ds=qsa(document,'div[role="dialog"]').filter(d=>!isPostDialog(d));
    return ds[0] || null;
  }
  function pickScrollBox(dlg){
    if(!dlg) return null;
    let best=dlg, delta=0;
    qsa(dlg,"div").forEach(n=>{
      const d=(n.scrollHeight||0)-(n.clientHeight||0);
      if(d>delta){ delta=d; best=n; }
    });
    return best;
  }
  function looksLikeUserRow(node){
    if(!node) return false;
    const hasButton = !!node.querySelector("button,div[role='button']");
    if(hasButton) return true;
    const hasAvatar = !!node.querySelector("img,svg");
    const hasLink   = !!node.querySelector("a[href^='/'],a[href^='https://www.instagram.com/']");
    return hasAvatar && hasLink;
  }

  async function openLikesDialog(){
    // 1) New UI: numeric-only counters anywhere (global scan – יותר חזק מהגרסה הישנה)
    const numVal = (t)=>{
      const m=(t||"").trim().match(/^(\d[\d,.\s]*)$/);
      return m ? Number(m[1].replace(/[^\d]/g,"")) : null;
    };
    const numericNodes = Array.from(document.querySelectorAll("span, a, div"))
      .filter(el => visible(el) && numVal(el.textContent) !== null)
      .sort((a,b)=> (numVal(b.textContent)||0) - (numVal(a.textContent)||0));

    if(numericNodes.length){
      const base = numericNodes[0];
      const target = base.closest("button, a, [role='button']") || base;
      clickHard(target);
    }

    // 2) Legacy: old liked_by link (אם קיים)
    let a = document.querySelector('a[href*="/liked_by/"]');
    if(a && visible(a)){ clickHard(a); }
    if(!pickAnyDialog()){
      const c=qsa(document,'section a[href*="/liked_by/"], header a[href*="/liked_by/"]');
      if(c.length){ clickHard(c[0]); }
    }

    // Wait for dialog
    for(let i=0;i<40;i++){
      if(pickLikesDialog()) return true;
      await sleep(200);
    }
    return !!pickLikesDialog();
  }

  if(!await openLikesDialog()) return done({ok:true, likers:[], seconds:0});

  const t0 = Date.now();
  let dlg = pickLikesDialog(); if(!dlg) return done({ok:true, likers:[], seconds:0});
  let box = pickScrollBox(dlg) || dlg;
  try{ box.scrollTop = 0; }catch(e){}

  const seen = Object.create(null);
  let idle=0, lastCnt=0;

  while(true){
    if((Date.now()-t0)/1000 > MAX_SECONDS) break;
    if(Object.keys(seen).length >= MAX_USERS) break;

    const anchors = box.querySelectorAll("a[href^='/'],a[href^='http']");
    for(const a of anchors){
      const href = a.getAttribute("href") || "";
      let user=null;
      if(href.startsWith("/")){
        const parts=href.split("/").filter(Boolean);
        if(parts.length===1 && /^[a-z0-9._]{1,30}$/i.test(parts[0])) user=parts[0];
      }else{
        try{
          const u=new URL(href);
          const p=u.pathname.split("/").filter(Boolean);
          if(p.length===1 && /^[a-z0-9._]{1,30}$/i.test(p[0])) user=p[0];
        }catch(e){}
      }
      if(!user) continue;

      let n=a; let ok=false;
      for(let h=0; h<8 && n; h++, n=n.parentElement){
        if(n.querySelector && looksLikeUserRow(n)){ ok=true; break; }
      }
      if(!ok) continue;

      if(!seen[user]){
        seen[user] = { username: user, username_url: "https://www.instagram.com/"+user+"/", media_url: location.href };
      }
    }

    try{ box.scrollTop = box.scrollTop + 900; }catch(e){}
    await sleep(300);

    const cnt = Object.keys(seen).length;
    if(cnt>lastCnt){ lastCnt=cnt; idle=0; } else { idle++; }
    if(idle>=60){
      const nb = pickScrollBox(pickLikesDialog());
      if(nb && nb!==box){ box=nb; idle=0; } else break;
    }
  }

  done({ok:true, likers:Object.values(seen), seconds: (Date.now()-t0)/1000 });
})().catch(e=>done({ok:false, error:String(e&&(e.stack||e.message||e))}));
"""

# ---------- Page helpers ----------
def wait_article(wait: WebDriverWait) -> None:
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article")))
    except Exception:
        pass

def collect_profile_links(driver: webdriver.Chrome, wait: WebDriverWait, username: str, limit: Optional[int]) -> List[str]:
    url = f"https://www.instagram.com/{username}/"
    print("➡  Opening profile:", url)
    if not safe_get(driver, url):
        print("❌ Failed to open profile page.")
        return []
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "header")))
    
    seen = set()
    ordered_links = []
    no_new_rounds = 0
    MAX_NO_NEW = 15 
    
    while True:
        cards = driver.find_elements(By.XPATH, "//a[contains(@href,'/p/') or contains(@href,'/reel/')]")
        added = 0
        for c in cards:
            href = c.get_attribute("href")
            if href and ("/p/" in href or "/reel/" in href) and href not in seen:
                seen.add(href)
                ordered_links.append(href)
                added += 1
                
        if limit and len(ordered_links) >= limit:
            break
            
        if cards:
           
            driver.execute_script("arguments[0].scrollIntoView(true);", cards[-1])
        else:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
        time.sleep(5) 
        
        if added == 0:
            no_new_rounds += 1
        else:
            no_new_rounds = 0
            
        if no_new_rounds >= MAX_NO_NEW:
            break
            
    print(f"✅ Collected {len(ordered_links)} post links (newest → oldest)")
    return ordered_links

def scrape_post_meta(post_url: str,
                     shortcode: str,
                     driver: webdriver.Chrome,
                     wait: WebDriverWait,
                     client: Optional["httpx.Client"]) -> Tuple[Optional[str], List[Dict], Optional[bool]]:
    """
    Returns: (posted_at_date_str, first_comments_rows, has_more_comments?)
    1) Try GraphQL with proper referer (p/ or reel/)
    2) Fallback to DOM: <time datetime> or application/ld+json
    """
    posted_at = None
    first_comments_rows: List[Dict] = []
    has_more: Optional[bool] = None

    # --- GraphQL ---
    if client:
        try:
            media = graphql_post(post_url, shortcode, client)
            ts = media.get("taken_at_timestamp") or media.get("taken_at")
            posted_at = to_date_str(ts)

            edge = (media.get("edge_media_to_parent_comment") or {})
            edges = (edge.get("edges") or [])
            page_info = edge.get("page_info") or {}
            has_more = bool(page_info.get("has_next_page"))
            for e in edges:
                n = (e.get("node") or {})
                owner = (n.get("owner") or {})
                first_comments_rows.append({
                    "username": owner.get("username",""),
                    "comment": n.get("text",""),
                    "posted_at": n.get("created_at",""),
                    "media_url": post_url
                })
            return posted_at, first_comments_rows, has_more
        except Exception as e:
            print(f"⚠ GraphQL failed for comments/meta: {e}")
            has_more = True  # trigger Selenium in AUTO

    # --- DOM fallback ---
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article")))
    except Exception:
        pass

    try:
        t = driver.find_elements(By.CSS_SELECTOR, "article time, header time, time")
        if t:
            dt = (t[0].get_attribute("datetime") or t[0].text or "").strip()
            if dt:
                posted_at = dt
    except Exception:
        pass

    if not posted_at:
        try:
            scripts = driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']")
            for s in scripts:
                txt = s.get_attribute("textContent") or ""
                if not txt.strip(): continue
                try:
                    data = json.loads(txt)
                except Exception:
                    continue

                def pick(d: dict) -> Optional[str]:
                    if not isinstance(d, dict): return None
                    for k in ("uploadDate", "datePublished", "dateCreated"):
                        v = d.get(k)
                        if v: return str(v)
                    return None

                if isinstance(data, dict):
                    v = pick(data)
                    if v: posted_at = v; break
                elif isinstance(data, list):
                    for obj in data:
                        v = pick(obj)
                        if v: posted_at = v; break
                if posted_at: break
        except Exception:
            pass

    # normalize to YYYY-MM-DD
    posted_at = to_date_str(posted_at)
    return posted_at, first_comments_rows, has_more

def selenium_comments(driver: webdriver.Chrome) -> List[Dict]:
    try:
        res = driver.execute_async_script(JS_COMMENTS)
        if res and res.get("ok"):
            return res.get("comments", [])
    except Exception as e:
        print("⚠ Selenium comments failed:", e)
    return []

def selenium_likers(driver: webdriver.Chrome,
                    likes_mode: str, max_likers: int, max_seconds: int) -> Tuple[List[Dict], int]:
    if likes_mode == "off":
        return [], 0
    try:
        driver.execute_script(
            "window.LIKES_CFG = {maxUsers: arguments[0], maxSeconds: arguments[1]};",
            int(max_likers),
            int(max_seconds if likes_mode == "fast" else max_seconds * 2)
        )
    except Exception:
        pass
    try:
        res = driver.execute_async_script(JS_LIKERS)
        if res and res.get("ok"):
            return res.get("likers", []), int(res.get("seconds", 0))
    except Exception as e:
        print("⚠ Selenium likers failed:", e)
    return [], 0

# ---------- Main ----------
def main():
    reset_processed_if_stale(args.reset_daily)
    processed = load_processed()

    driver, wait = selenium_setup(args.headless)
    client = make_client()  # may be None

    total_posts = 0
    total_comments = 0
    total_likers = 0

    try:
        links = collect_profile_links(driver, wait, args.profile, args.limit)
       
        for idx, url in enumerate(links, 1):
            shortcode = parse_shortcode(url)

            if shortcode in processed:
                print("⏭ skipping (already processed)")
                continue

            if not safe_get(driver, url, retries=4, base_sleep=4):
                print("❌ Giving up on this post due to repeated navigation errors.")
                continue

            wait_article(wait)

            posted_at, first_comments_rows, has_more = scrape_post_meta(url, shortcode, driver, wait, client)

            if args.comments == "force":
                need_comments_selenium = True
            elif args.comments == "off":
                need_comments_selenium = False
            else:
                need_comments_selenium = ((client is None) or (has_more is True) or (len(first_comments_rows) == 0))

            sel_comments_rows = selenium_comments(driver) if need_comments_selenium else []

            # Merge comments (dedupe per post)
            comment_seen = set()
            comments_rows: List[Dict] = []
            for r in (first_comments_rows + sel_comments_rows):
                key = (r.get("username",""), r.get("comment",""))
                if key in comment_seen:
                    continue
                comment_seen.add(key)
                comments_rows.append({
                    "post_shortcode": shortcode,
                    "username": r.get("username",""),
                    "comment": r.get("comment",""),
                    "posted_at": r.get("posted_at",""),
                    "media_url": r.get("media_url", url)
                })

            # Likers
            max_secs = args.max_seconds_likers
            likers_rows, took_s = selenium_likers(driver, args.likes_mode, args.max_likers, max_secs)
            if took_s:
                print(f"⏱ likers: {len(likers_rows)} users in ~{took_s}s")

            likers_rows = [
                {
                    "post_shortcode": shortcode,
                    "username": r.get("username",""),
                    "username_url": r.get("username_url",""),
                    "media_url": r.get("media_url", url)
                } for r in likers_rows
            ]

            # Append to CSVs
            append_csv(
                CSV_POSTS,
                [{"post_shortcode": shortcode, "post_url": url, "posted_at": posted_at or ""}],
                ["post_shortcode","post_url","posted_at"]
            )
            append_csv(
                CSV_COMMENTS,
                comments_rows,
                ["post_shortcode","username","comment","posted_at","media_url"]
            )
            append_csv(
                CSV_LIKERS,
                likers_rows,
                ["post_shortcode","username","username_url","media_url"]
            )

            total_posts += 1
            total_comments += len(comments_rows)
            total_likers += len(likers_rows)

            mark_processed(shortcode)

            if args.pause_every and args.pause_seconds:
                if idx % args.pause_every == 0 and idx < len(links):
                    print(f"⏸ pause {args.pause_seconds}s (progress {idx}/{len(links)})")
                    time.sleep(args.pause_seconds)

        print(f"✅ Done. Posts: {total_posts}, Comments: {total_comments}, Likers: {total_likers}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    start_time = time.time()
    print(f"\n🚀 Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        main()
    finally:
        end_time = time.time()
        duration = end_time - start_time
        minutes, seconds = divmod(duration, 60)
        print(f"\n🏁 End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱ Total duration: {int(minutes)} minutes and {int(seconds)} seconds")