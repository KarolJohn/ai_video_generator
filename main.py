import os
import random
import requests
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from gtts import gTTS
from moviepy.editor import (AudioFileClip, CompositeAudioClip, VideoFileClip,
                            concatenate_videoclips, vfx)

# --- MODELS ---
class VideoRequest(BaseModel):
    topic: str

# --- NEW WAY FOR VERCEL ---
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- SETUP ---
try:
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    print(f"Error configuring Google AI: {e}")

app = FastAPI()

# --- ROUTES ---
@app.get("/")
async def read_root():
    """Serves the main HTML page."""
    return FileResponse('index.html')

@app.post("/create_video")
async def create_video(request: VideoRequest):
    """Generates a video based on the provided topic."""
    topic = request.topic
    print(f"Received topic: {topic}")

    audio_filename = "voiceover.mp3"
    video_paths = []
    
    try:
        # 1. --- AI SCRIPT GENERATION ---
        prompt = f"You are a scriptwriter for short videos. Write a voiceover script about '{topic}'. The script must be less than 40 words. Do not include any labels like 'VOICEOVER:', sound effects, or asterisks. Only output the raw text to be spoken."
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(prompt)
        raw_script = response.text.strip()
        script = raw_script.replace("**VOICEOVER:**", "").replace("**", "").strip()
        if not script:
            raise ValueError("AI returned an empty script.")
        print(f"Generated script: {script}")

        # 2. --- TEXT-TO-SPEECH ---
        tts = gTTS(text=script, lang='en', tld='com.au')
        tts.save(audio_filename)
        print(f"Audio saved as {audio_filename}")

        # 3. --- FINDING VIDEO CLIPS ---
        headers = {"Authorization": PEXELS_API_KEY}
        # --- CHANGE 1: Ask for 2 videos instead of 3 ---
        query_url = f"https://api.pexels.com/videos/search?query={topic}&per_page=2&orientation=portrait"
        response = requests.get(query_url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch videos from Pexels.")
        videos = response.json().get("videos", [])
        if not videos:
            raise HTTPException(status_code=404, detail=f"No videos found for topic: {topic}")
        
        for i, video in enumerate(videos):
            video_link = next((f['link'] for f in video['video_files'] if f['quality'] == 'sd'), None)
            if not video_link:
                continue
            video_data = requests.get(video_link).content
            video_path = f"video_{i}.mp4"
            with open(video_path, 'wb') as handler:
                handler.write(video_data)
            video_paths.append(video_path)
        print(f"Downloaded {len(video_paths)} video clips.")

        if not video_paths:
            raise HTTPException(status_code=404, detail="Could not download any usable video clips for this topic.")
        
        # 4. --- VIDEO ASSEMBLY ---
        voiceover_clip = AudioFileClip(audio_filename)
        music_files = os.listdir("music")
        random_music_file = random.choice(music_files)
        music_path = os.path.join("music", random_music_file)
        
        music_clip = AudioFileClip(music_path)
        if music_clip.duration < voiceover_clip.duration:
            music_clip = music_clip.fx(vfx.loop, duration=voiceover_clip.duration)
        else:
            music_clip = music_clip.subclip(0, voiceover_clip.duration)
        music_clip = music_clip.volumex(0.1)
        
        combined_audio = CompositeAudioClip([voiceover_clip, music_clip])
        clip_duration = voiceover_clip.duration / len(video_paths)
        
        final_clips = []
        opened_video_clips = [] 
        for path in video_paths:
            clip = VideoFileClip(path)
            opened_video_clips.append(clip)
            trimmed_clip = clip.subclip(0, clip_duration)
            # --- CHANGE 2: Resize to 480p to save even more memory ---
            resized_clip = trimmed_clip.resize(height=480) 
            final_clips.append(resized_clip)
        
        final_video = concatenate_videoclips(final_clips)
        final_video.audio = combined_audio

        output_filename = f"{topic.replace(' ', '_')}_video.mp4"
        final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac')
        print(f"Video saved as {output_filename}!")

        voiceover_clip.close()
        music_clip.close()
        for clip in opened_video_clips:
            clip.close()
    
    finally:
        # 5. --- CLEANUP ---
        if os.path.exists(audio_filename):
            os.remove(audio_filename)
        for path in video_paths:
            if os.path.exists(path):
                os.remove(path)
        print("Cleaned up temporary files.")

    return {"message": f"Video created successfully: {output_filename}"}