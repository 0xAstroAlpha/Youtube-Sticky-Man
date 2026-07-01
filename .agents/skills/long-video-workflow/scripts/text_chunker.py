import argparse
import os
import re

def chunk_file(input_file, out_dir, max_chars=5000):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Split strictly by double newline (paragraph boundary)
    paragraphs = content.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for p in paragraphs:
        # If a single paragraph is bizarrely longer than max_chars, split by sentences
        if len(p) > max_chars:
            sentences = re.split(r'(?<=[.!?]) +', p)
            for s in sentences:
                if len(current_chunk) + len(s) < max_chars:
                    current_chunk += s + " "
                else:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = s + " "
        else:
            if len(current_chunk) + len(p) < max_chars:
                current_chunk += p + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
            
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        
    for i, c in enumerate(chunks):
        out_path = os.path.join(out_dir, f"chunk_{i+1}.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(c)
        print(f"Created {out_path} ({len(c)} chars)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intelligent Text Chunker")
    parser.add_argument('--input', type=str, required=True, help='Path to the original script text file')
    parser.add_argument('--out-dir', type=str, required=True, help='Output directory for the chunks')
    parser.add_argument('--max-chars', type=int, default=5000, help='Maximum characters per chunk (default 5000)')
    args = parser.parse_args()
    
    chunk_file(args.input, args.out_dir, args.max_chars)
