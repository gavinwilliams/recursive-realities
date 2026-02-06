#!/usr/bin/env python3
"""
Generate audiobook from markdown file using Eleven Labs API.
"""
import os
import sys
import re
from pathlib import Path
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from pydub import AudioSegment
import tempfile


def markdown_to_text(markdown_content):
    """
    Convert markdown content to plain text for audio narration.
    Removes markdown formatting while preserving the narrative flow.
    """
    text = markdown_content
    
    # Remove markdown links but keep the text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Remove images
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
    
    # Remove horizontal rules
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    # Convert headers to plain text with pauses
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1.\n', text, flags=re.MULTILINE)
    
    # Remove bold/italic markers
    text = re.sub(r'\*\*\*([^\*]+)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^\*]+)\*', r'\1', text)
    text = re.sub(r'___([^_]+)___', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    
    # Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Clean up multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    # Clean up multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()


def split_text_into_chunks(text, max_length=9500):
    """
    Split text into chunks that are under the max_length limit.
    Tries to split on paragraph boundaries, then sentence boundaries.
    
    Args:
        text: The text to split
        max_length: Maximum length for each chunk (default 9500 to leave buffer)
    
    Returns:
        List of text chunks
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split into paragraphs first
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # If a single paragraph is too long, split it by sentences
        if len(paragraph) > max_length:
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                # If even a single sentence is too long, force split it
                if len(sentence) > max_length:
                    # Split at max_length boundaries, trying to break on spaces
                    while len(sentence) > max_length:
                        split_point = sentence.rfind(' ', 0, max_length)
                        if split_point == -1:
                            split_point = max_length
                        
                        chunk_part = sentence[:split_point].strip()
                        if current_chunk:
                            if len(current_chunk) + len(chunk_part) + 1 <= max_length:
                                current_chunk += " " + chunk_part
                            else:
                                chunks.append(current_chunk)
                                current_chunk = chunk_part
                        else:
                            current_chunk = chunk_part
                        
                        sentence = sentence[split_point:].strip()
                    
                    # Add remaining part
                    if sentence:
                        if current_chunk and len(current_chunk) + len(sentence) + 1 <= max_length:
                            current_chunk += " " + sentence
                        elif current_chunk:
                            chunks.append(current_chunk)
                            current_chunk = sentence
                        else:
                            current_chunk = sentence
                else:
                    # Normal sentence
                    if current_chunk and len(current_chunk) + len(sentence) + 1 <= max_length:
                        current_chunk += " " + sentence
                    elif current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = sentence
                    else:
                        current_chunk = sentence
        else:
            # Paragraph fits, try to add it to current chunk
            if current_chunk and len(current_chunk) + len(paragraph) + 2 <= max_length:
                current_chunk += "\n\n" + paragraph
            elif current_chunk:
                chunks.append(current_chunk)
                current_chunk = paragraph
            else:
                current_chunk = paragraph
    
    # Add the last chunk if it exists
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def generate_audiobook(input_file, output_file, api_key, voice_id=None, model_id=None):
    """
    Generate audiobook from markdown file using Eleven Labs API.
    If text exceeds the API limit, it will be split into chunks and combined.
    
    Args:
        input_file: Path to input markdown file
        output_file: Path to output audio file
        api_key: Eleven Labs API key
        voice_id: Voice ID to use (default: Rachel - 21m00Tcm4TlvDq8ikWAM, a calm, clear voice)
                  This is an Eleven Labs voice identifier. Available voices can be found at:
                  https://elevenlabs.io/voices
        model_id: Model ID to use (default: eleven_multilingual_v2)
                  Available models: https://elevenlabs.io/docs/api-reference/text-to-speech
    """
    # Set defaults
    if voice_id is None:
        env_voice_id = os.environ.get('ELEVEN_LABS_VOICE_ID', '21m00Tcm4TlvDq8ikWAM')
        print(f"🔍 ELEVEN_LABS_VOICE_ID from environment: '{env_voice_id}'")
        voice_id = env_voice_id
    if model_id is None:
        model_id = os.environ.get('ELEVEN_LABS_MODEL_ID', 'eleven_multilingual_v2')
    
    print(f"🎙️  Reading markdown file: {input_file}")
    
    # Read the markdown file
    with open(input_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    # Convert to plain text
    print("📝 Converting markdown to plain text...")
    text_content = markdown_to_text(markdown_content)
    
    # Check text length
    text_length = len(text_content)
    print(f"📊 Text length: {text_length} characters")
    
    if text_length == 0:
        print("❌ Error: No text content found after markdown conversion")
        sys.exit(1)
    
    # Initialize Eleven Labs client
    print("🔌 Connecting to Eleven Labs API...")
    client = ElevenLabs(api_key=api_key)
    
    # Eleven Labs has a 10,000 character limit for standard TTS
    MAX_CHUNK_SIZE = 9500  # Use 9500 to leave some buffer
    
    # Check if we need to split the text
    if text_length > MAX_CHUNK_SIZE:
        print(f"⚠️  Text exceeds Eleven Labs limit of 10,000 characters")
        print(f"📦 Splitting text into chunks...")
        text_chunks = split_text_into_chunks(text_content, MAX_CHUNK_SIZE)
        print(f"📦 Split into {len(text_chunks)} chunks")
        
        # Generate audio for each chunk
        audio_segments = []
        temp_files = []
        
        try:
            for i, chunk in enumerate(text_chunks):
                print(f"\n🎵 Generating audio for chunk {i+1}/{len(text_chunks)} ({len(chunk)} characters)...")
                
                audio_generator = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=chunk,
                    model_id=model_id,
                    voice_settings=VoiceSettings(
                        stability=0.5,
                        similarity_boost=0.75,
                        style=0.0,
                        use_speaker_boost=True
                    )
                )
                
                # Write chunk to temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                temp_files.append(temp_file.name)
                
                with open(temp_file.name, 'wb') as f:
                    for audio_chunk in audio_generator:
                        f.write(audio_chunk)
                
                print(f"✅ Chunk {i+1} generated")
                
                # Load audio segment
                audio_segment = AudioSegment.from_mp3(temp_file.name)
                audio_segments.append(audio_segment)
            
            # Combine all audio segments
            print(f"\n🔗 Combining {len(audio_segments)} audio chunks...")
            combined_audio = audio_segments[0]
            for segment in audio_segments[1:]:
                combined_audio += segment
            
            # Export combined audio
            print(f"💾 Writing combined audio to: {output_file}")
            combined_audio.export(output_file, format='mp3')
            
            print(f"✅ Audiobook generated successfully: {output_file}")
            
            # Get file size
            file_size = os.path.getsize(output_file)
            file_size_mb = file_size / (1024 * 1024)
            print(f"📦 File size: {file_size_mb:.2f} MB")
            
        except Exception as e:
            print(f"❌ Error generating audiobook: {e}")
            sys.exit(1)
        finally:
            # Clean up temporary files
            print("🧹 Cleaning up temporary files...")
            for temp_file in temp_files:
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass  # Ignore file deletion errors
    else:
        # Text is short enough, generate in one go
        print(f"🎵 Generating audiobook with voice ID: {voice_id}")
        print("⏳ This may take several minutes for longer texts...")
        
        try:
            # Generate audio using the text-to-speech API
            audio_generator = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text_content,
                model_id=model_id,
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            )
            
            # Write audio to file
            print(f"💾 Writing audio to: {output_file}")
            with open(output_file, 'wb') as f:
                for chunk in audio_generator:
                    f.write(chunk)
            
            print(f"✅ Audiobook generated successfully: {output_file}")
            
            # Get file size
            file_size = os.path.getsize(output_file)
            file_size_mb = file_size / (1024 * 1024)
            print(f"📦 File size: {file_size_mb:.2f} MB")
            
        except Exception as e:
            print(f"❌ Error generating audiobook: {e}")
            sys.exit(1)


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python generate_audiobook.py <input_markdown> <output_audio>")
        print("Example: python generate_audiobook.py book.md book.mp3")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # Get API key from environment
    api_key = os.environ.get('ELEVEN_LABS_API_KEY')
    if not api_key:
        print("❌ Error: ELEVEN_LABS_API_KEY environment variable not set")
        sys.exit(1)
    
    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"❌ Error: Input file not found: {input_file}")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Generate audiobook
    generate_audiobook(input_file, output_file, api_key)


if __name__ == '__main__':
    main()
