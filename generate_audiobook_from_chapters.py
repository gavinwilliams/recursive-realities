#!/usr/bin/env python3
"""
Generate audiobook from multiple chapter markdown files using Eleven Labs API.
Each chapter is generated separately and then combined into a single audiobook.
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


def generate_audio_for_chapter(client, text, voice_id, model_id, chapter_name):
    """
    Generate audio for a single chapter.
    If the chapter exceeds the API limit, it will be split into chunks.
    
    Args:
        client: ElevenLabs client instance
        text: The text content to convert
        voice_id: Voice ID to use
        model_id: Model ID to use
        chapter_name: Name of the chapter for logging
    
    Returns:
        AudioSegment containing the chapter audio
    """
    print(f"\n🎵 Generating audio for: {chapter_name}")
    print(f"   Text length: {len(text)} characters")
    
    MAX_CHUNK_SIZE = 9500
    
    # Check if we need to split the chapter
    if len(text) > MAX_CHUNK_SIZE:
        print(f"   ⚠️  Chapter exceeds limit, splitting into chunks...")
        text_chunks = split_text_into_chunks(text, MAX_CHUNK_SIZE)
        print(f"   📦 Split into {len(text_chunks)} chunks")
        
        audio_segments = []
        
        for i, chunk in enumerate(text_chunks):
            print(f"      - Chunk {i+1}/{len(text_chunks)}: {len(chunk)} characters")
            
            # Generate audio for this chunk
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
            
            # Write to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            with open(temp_file.name, 'wb') as f:
                for audio_chunk in audio_generator:
                    f.write(audio_chunk)
            
            # Load audio segment
            audio_segment = AudioSegment.from_mp3(temp_file.name)
            audio_segments.append(audio_segment)
            
            # Clean up temp file
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass  # Ignore file deletion errors
        
        # Combine chunks for this chapter
        print(f"   🔗 Combining {len(audio_segments)} chunks for this chapter...")
        combined_audio = audio_segments[0]
        for segment in audio_segments[1:]:
            combined_audio += segment
        
        print(f"   ✅ Chapter audio generated (from {len(text_chunks)} chunks)")
        return combined_audio
    else:
        # Chapter is short enough, generate in one go
        # Generate audio using the text-to-speech API
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.0,
                use_speaker_boost=True
            )
        )
        
        # Write to temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        with open(temp_file.name, 'wb') as f:
            for chunk in audio_generator:
                f.write(chunk)
        
        file_size = os.path.getsize(temp_file.name)
        file_size_mb = file_size / (1024 * 1024)
        print(f"   ✅ Audio generated: {file_size_mb:.2f} MB")
        
        # Load audio segment
        audio_segment = AudioSegment.from_mp3(temp_file.name)
        
        # Clean up temp file
        try:
            os.unlink(temp_file.name)
        except OSError:
            pass  # Ignore file deletion errors
        
        return audio_segment


def generate_audiobook_from_chapters(chapter_files, output_file, api_key, voice_id=None, model_id=None):
    """
    Generate audiobook from multiple chapter markdown files.
    
    Args:
        chapter_files: List of paths to chapter markdown files (in order)
        output_file: Path to output audio file
        api_key: Eleven Labs API key
        voice_id: Voice ID to use (default: Rachel)
        model_id: Model ID to use (default: eleven_multilingual_v2)
    """
    # Set defaults
    if voice_id is None:
        env_voice_id = os.environ.get('ELEVEN_LABS_VOICE_ID', '21m00Tcm4TlvDq8ikWAM')
        print(f"🔍 ELEVEN_LABS_VOICE_ID from environment: '{env_voice_id}'")
        voice_id = env_voice_id
    if model_id is None:
        model_id = os.environ.get('ELEVEN_LABS_MODEL_ID', 'eleven_multilingual_v2')
    
    print(f"🎙️  Generating audiobook from {len(chapter_files)} chapters")
    print(f"📂 Output file: {output_file}")
    
    # Verify all chapter files exist
    for chapter_file in chapter_files:
        if not os.path.exists(chapter_file):
            print(f"❌ Error: Chapter file not found: {chapter_file}")
            sys.exit(1)
    
    # Initialize Eleven Labs client with extended timeout for large audio generation
    print("🔌 Connecting to Eleven Labs API...")
    client = ElevenLabs(api_key=api_key, timeout=300.0)
    
    audio_segments = []
    
    try:
        # Process each chapter
        for i, chapter_file in enumerate(chapter_files):
            chapter_name = os.path.basename(chapter_file)
            print(f"\n{'='*70}")
            print(f"📖 Chapter {i+1}/{len(chapter_files)}: {chapter_name}")
            print(f"{'='*70}")
            
            # Read the markdown file
            with open(chapter_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            
            # Convert to plain text
            text_content = markdown_to_text(markdown_content)
            
            if len(text_content) == 0:
                print(f"   ⚠️  Warning: No text content found, skipping chapter")
                continue
            
            # Generate audio for this chapter (handles chunking internally if needed)
            audio_segment = generate_audio_for_chapter(
                client, text_content, voice_id, model_id, chapter_name
            )
            audio_segments.append(audio_segment)
        
        if not audio_segments:
            print("❌ Error: No audio segments generated")
            sys.exit(1)
        
        # Combine all audio segments
        print(f"\n{'='*70}")
        print(f"🔗 Combining {len(audio_segments)} chapter audio files...")
        print(f"{'='*70}")
        
        combined_audio = audio_segments[0]
        for segment in audio_segments[1:]:
            combined_audio += segment
        
        # Export combined audio
        print(f"💾 Writing combined audiobook to: {output_file}")
        combined_audio.export(output_file, format='mp3')
        
        print(f"\n✅ Audiobook generated successfully!")
        
        # Get final file size
        file_size = os.path.getsize(output_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"📦 Final audiobook size: {file_size_mb:.2f} MB")
        
    except Exception as e:
        print(f"\n❌ Error generating audiobook: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python generate_audiobook_from_chapters.py <output_audio> <chapter1.md> <chapter2.md> ...")
        print("Example: python generate_audiobook_from_chapters.py book.mp3 ch1.md ch2.md ch3.md")
        sys.exit(1)
    
    output_file = sys.argv[1]
    chapter_files = sys.argv[2:]
    
    if not chapter_files:
        print("❌ Error: No chapter files provided")
        sys.exit(1)
    
    # Get API key from environment
    api_key = os.environ.get('ELEVEN_LABS_API_KEY')
    if not api_key:
        print("❌ Error: ELEVEN_LABS_API_KEY environment variable not set")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Generate audiobook from chapters
    generate_audiobook_from_chapters(chapter_files, output_file, api_key)


if __name__ == '__main__':
    main()
