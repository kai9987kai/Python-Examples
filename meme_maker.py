import sys
import os
from PIL import Image, ImageDraw, ImageFont

def get_font(size):
    """Attempt to load a system TrueType font, fallback to default if not found."""
    system_fonts = [
        "C:\\Windows\\Fonts\\Arial.ttf",            # Windows
        "/System/Library/Fonts/Helvetica.ttc",      # Mac
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Linux
    ]
    for font_path in system_fonts:
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size=size)
    print("Warning: System font not found. Using default PIL font.")
    return ImageFont.load_default()

def draw_text_with_background(draw, text, font, text_color, img_size, bg_opacity=160):
    """
    Dynamically calculates text size, wraps it, draws a semi-transparent 
    background box for readability, and centers the text.
    """
    img_w, img_h = img_size
    max_text_width = img_w - 100  # 50px padding on each side
    
    # Simple text wrapping logic
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_text_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
            
    if current_line:
        lines.append(current_line)

    # Calculate total block size
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
        
    total_height = sum(line_heights) + (len(lines) * 10) # 10px line spacing
    max_width = max(line_widths) if line_widths else 0
    
    # Calculate starting positions to center the block
    start_x = (img_w - max_width) / 2
    start_y = (img_h - total_height) / 2
    
    # Determine background color based on text color brightness
    # If text is bright (like white), make background dark, and vice versa
    brightness = sum(text_color) / 3
    bg_color = (0, 0, 0, bg_opacity) if brightness > 127 else (255, 255, 255, bg_opacity)
    
    # Draw background rectangle with 20px padding
    pad = 20
    draw.rectangle(
        [start_x - pad, start_y - pad, start_x + max_width + pad, start_y + total_height + pad],
        fill=bg_color
    )
    
    # Draw text line by line
    current_y = start_y
    for i, line in enumerate(lines):
        # Center each line individually within the max width block
        line_x = start_x + (max_width - line_widths[i]) / 2
        draw.text((line_x, current_y), line, fill=text_color, font=font)
        current_y += line_heights[i] + 10

def input_par():
    """Gathers user input interactively with validation."""
    print('--- Image Text Inserter ---')
    text = input('Enter the text to insert in image:\n> ')
    
    while True:
        try:
            size = int(input('Enter the desired size of the text (e.g., 50):\n> '))
            if size > 0: break
            print("Size must be greater than 0.")
        except ValueError:
            print("Invalid input. Please enter an integer.")

    while True:
        try:
            color_str = input('Enter the color for the text (r, g, b) e.g., 255 255 255:\n> ')
            color_value = tuple(int(i) for i in color_str.replace(',', ' ').split())
            if len(color_value) == 3 and all(0 <= c <= 255 for c in color_value):
                break
            print("Please enter exactly 3 values between 0 and 255.")
        except ValueError:
            print("Invalid input. Use numbers separated by spaces or commas.")
            
    return text, size, color_value

def main():
    # Allow passing image path as argument, or prompt for it
    if len(sys.argv) > 1:
        path_to_image = sys.argv[1]
    else:
        path_to_image = input("Enter path to image file:\n> ")

    if not os.path.exists(path_to_image):
        print(f"Error: File '{path_to_image}' not found.")
        sys.exit(1)

    try:
        image_file = Image.open(path_to_image)
        image_file = image_file.convert("RGBA")
    except Exception as e:
        print(f"Error opening image: {e}")
        sys.exit(1)

    print(f"Image loaded successfully. Size: {image_file.size}")
    text, size, color_value = input_par()
    
    font = get_font(size)
    
    # Initialize drawing context
    draw = ImageDraw.Draw(image_file)
    
    # Draw the text and dynamic background
    draw_text_with_background(draw, text, font, color_value, image_file.size)
    
    # Show the image (Note: .show() creates a temporary file and opens it)
    image_file.show()

    # Save the file
    file_name = input('Enter the output file name (without extension):\n> ')
    
    # Default to PNG to preserve RGBA transparency, allow override
    output_ext = ".png"
    if file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
        # split extension to normalize
        file_name, output_ext = os.path.splitext(file_name)
        if output_ext.lower() in ('.jpg', '.jpeg'):
            # Flatten image if saving as JPEG (JPEG doesn't support alpha)
            background = Image.new("RGBA", image_file.size, (255, 255, 255))
            background.paste(image_file, mask=image_file.split()[3])
            image_file = background.convert('RGB')

    try:
        image_file.save(f"{file_name}{output_ext}")
        print(f"Image successfully saved as {file_name}{output_ext}")
    except Exception as e:
        print(f"Error saving file: {e}")

if __name__ == '__main__':
    main()
