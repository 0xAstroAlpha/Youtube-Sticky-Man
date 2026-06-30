import requests
import base64
import json
import argparse
import sys
import os
from dotenv import load_dotenv

load_dotenv()

def get_elevenlabs_tts_with_timestamps(api_key, text, voice_id="21m00Tcm4TlvDq8ikWAM", model_id="eleven_multilingual_v2", output_audio="output.mp3", output_json="transcript_word_aligned.json"):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    data = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    print(f"Calling ElevenLabs API (Voice: {voice_id}, Model: {model_id})...")
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        sys.exit(1)
        
    response_data = response.json()
    
    # 1. Decode and save audio
    audio_base64 = response_data.get("audio_base64")
    if audio_base64:
        audio_bytes = base64.b64decode(audio_base64)
        with open(output_audio, "wb") as f:
            f.write(audio_bytes)
        print(f"Saved audio to: {output_audio}")
        
    # 2. Extract and convert character alignment to word-level timestamps
    alignment = response_data.get("alignment")
    if alignment:
        characters = alignment.get('characters', [])
        start_times = alignment.get('character_start_times_seconds', [])
        end_times = alignment.get('character_end_times_seconds', [])
        
        words = []
        current_word = ""
        current_start = None
        
        for i, char in enumerate(characters):
            if char.strip() == "":
                if current_word:
                    words.append({
                        "word": current_word,
                        "start": round(current_start, 3),
                        "end": round(end_times[i-1], 3)
                    })
                    current_word = ""
                    current_start = None
            else:
                if current_word == "":
                    current_start = start_times[i]
                current_word += char
                
        # Catch the last word
        if current_word:
            words.append({
                "word": current_word,
                "start": round(current_start, 3),
                "end": round(end_times[-1], 3)
            })
            
        # Save transcript JSON
        transcript_data = {
            "text": text,
            "words": words
        }
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, ensure_ascii=False, indent=2)
            
        print(f"Saved word-level transcript to: {output_json}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ElevenLabs TTS with Word-Level Timestamps")
    parser.add_argument("--input-file", type=str, required=True, help="Path to text file")
    parser.add_argument("--voice-id", type=str, default="21m00Tcm4TlvDq8ikWAM", help="ElevenLabs Voice ID")
    parser.add_argument("--model-id", type=str, default="eleven_multilingual_v2", help="ElevenLabs Model ID")
    parser.add_argument("--out-audio", type=str, default="output.mp3", help="Output audio file path")
    parser.add_argument("--out-json", type=str, default="transcript_word_aligned.json", help="Output JSON transcript path")
    
    args = parser.parse_args()
    
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not found in .env")
        sys.exit(1)
        
    with open(args.input_file, 'r', encoding='utf-8') as f:
        text_content = f.read()
        
    get_elevenlabs_tts_with_timestamps(
        api_key=api_key,
        text=text_content,
        voice_id=args.voice_id,
        model_id=args.model_id,
        output_audio=args.out_audio,
        output_json=args.out_json
    )
