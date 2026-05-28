import google.generativeai as genai

genai.configure(api_key="AIzaSyCcJF_ESE1z6xhdhQlyFrcflAyYEs74E1I")

print("🔍 Searching for available models for your key...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print(f"Error connecting to Google API: {e}")