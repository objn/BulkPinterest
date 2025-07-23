# 📌 Pinterest Image Downloader with Playwright

A robust Python tool for downloading high-quality images from Pinterest boards or pins using headless browser automation with [Playwright](https://playwright.dev/). This script scrolls through Pinterest pages, extracts image URLs, and downloads them efficiently with fallback mechanisms for multiple quality levels.

## 🚀 Features

- ✅ Scrolls Pinterest pages to reveal and extract images dynamically
- 🎯 Selects best image quality available: `originals`, `1200x`, `736x`, etc.
- 🧠 Smart duplicate avoidance
- 🧪 Multi-selector and multi-strategy extraction for better reliability
- 📥 Parallel downloads with thread-safe counters
- 📊 Real-time progress bars via `tqdm`
- 📂 Output images neatly into a designated directory
- 🧵 Thread-safe and resilient error handling

## 📦 Requirements

- Python 3.10+
- [Playwright](https://playwright.dev/python/)
- [tqdm](https://github.com/tqdm/tqdm)
- [colorama](https://pypi.org/project/colorama/)
- [requests](https://pypi.org/project/requests/)

Install dependencies:

```bash
pip install -r requirements.txt
playwright install
```

📄 Usage
Create a .txt file (e.g. urls.txt) with Pinterest pin URLs (one per line):

https://www.pinterest.com/pin/123456789/
https://www.pinterest.com/pin/987654321/
...

Run the script:

```bash
python -m venv venv
```

```bash
venv\Scripts\activate
or
source venv\bin\activate
```
```bash
python pinterest.py urls.txt -m 100 -w 6 -o images -s 80
````

Arguments
Flag	Description	Default
input_file	Path to .txt file containing Pinterest URLs	required
-m, --max-downloads	Total number of images to download	50
-w, --workers	Number of parallel download threads	4
-o, --output	Output directory to save downloaded images	temp/
-s, --scrolls	Max scrolls per Pinterest page	100
