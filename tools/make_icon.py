"""Generate Finder's original magnifying-glass icon in Windows ICO format."""
from PIL import Image, ImageDraw
from pathlib import Path

def make_icon(destination="assets/finder.ico"):
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), radius=55, fill="#17172B")
    # subtle dual ring for a recognizable app icon at small sizes
    draw.ellipse((65, 46, 184, 165), outline="#B86CFF", width=19)
    draw.arc((65, 46, 184, 165), 210, 335, fill="#E5BBFF", width=8)
    draw.line((162, 149, 210, 198), fill="#B86CFF", width=25)
    draw.ellipse((195, 184, 222, 211), fill="#B86CFF")
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print(dest)

if __name__ == "__main__":
    make_icon()
