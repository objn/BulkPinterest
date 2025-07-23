#!/usr/bin/env python3
"""
Pinterest Image Downloader with Playwright
A tool to download all images from Pinterest pages by scrolling and collecting multiple images
"""

import os
import re
import sys
import time
import requests
import threading
import asyncio
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from colorama import init, Fore, Style
import argparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Initialize colorama for cross-platform colored output
init(autoreset=True)

class PinterestPlaywrightDownloader:
    def __init__(self, max_downloads=50, max_workers=4, output_dir="temp", max_scrolls=100):
        self.max_downloads = max_downloads
        self.max_workers = max_workers
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.max_scrolls = max_scrolls
        
        # Quality levels in order of preference (best to worst)
        self.quality_levels = ["originals", "1200x", "736x", "564x", "474x", "236x"]
        
        # Statistics
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_extractions = 0
        self.skipped_pages = []
        self.duplicate_count = 0
        
        # Thread lock for updating counters
        self.lock = threading.Lock()
        
        # Track downloaded files to avoid duplicates
        self.downloaded_files = set()
        
        # Session for requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    async def extract_all_images_from_page(self, pinterest_url, pbar_extract):
        """Scroll down Pinterest page and extract all image URLs using Playwright"""
        async with async_playwright() as p:
            try:
                # Launch browser
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-features=VizDisplayCompositor'
                    ]
                )
                
                # Create context with custom user agent
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = await context.new_page()
                
                # Set timeout for page loads
                page.set_default_timeout(10000)  # 10 seconds
                
                try:
                    # Navigate to Pinterest page
                    await page.goto(pinterest_url, wait_until='domcontentloaded')
                    
                    # Wait for initial images to load
                    try:
                        await page.wait_for_selector('img', timeout=2000)
                    except PlaywrightTimeoutError:
                        with self.lock:
                            self.skipped_pages.append(pinterest_url)
                        await browser.close()
                        return []
                    
                    all_image_urls = set()
                    scrolls_done = 0
                    no_new_content_count = 0
                    last_image_count = 0
                    
                    while scrolls_done < self.max_scrolls:
                        # Scroll to bottom
                        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                        
                        # Wait for new content to load
                        await asyncio.sleep(2)
                        
                        # Get all image elements
                        img_elements = await page.query_selector_all('img')
                        
                        for img in img_elements:
                            try:
                                src = await img.get_attribute('src')
                                if src and "i.pinimg.com" in src and not src.lower().endswith('.gif'):
                                    # Extract the image hash
                                    image_hash = self.extract_hash_from_url(src)
                                    if image_hash:
                                        all_image_urls.add(image_hash)
                            except Exception:
                                continue
                        
                        # Check for new content
                        current_image_count = len(all_image_urls)
                        if current_image_count == last_image_count:
                            no_new_content_count += 1
                            if no_new_content_count >= 3:  # Stop if no new images for 3 scrolls
                                break
                        else:
                            no_new_content_count = 0
                            last_image_count = current_image_count
                        
                        scrolls_done += 1
                        
                        # Update progress
                        pbar_extract.set_description(
                            f"{Fore.BLUE}Scrolling{Style.RESET_ALL} | {Fore.GREEN}Images: {len(all_image_urls)}{Style.RESET_ALL} | {Fore.CYAN}Scroll: {scrolls_done}/{self.max_scrolls}{Style.RESET_ALL}"
                        )
                        
                        # Break if we have enough images
                        if len(all_image_urls) >= self.max_downloads:
                            break
                    
                    await browser.close()
                    return list(all_image_urls)
                    
                except PlaywrightTimeoutError:
                    with self.lock:
                        self.skipped_pages.append(pinterest_url)
                    await browser.close()
                    return []
                    
            except Exception as e:
                with self.lock:
                    self.skipped_pages.append(pinterest_url)
                return []

    def extract_hash_from_url(self, img_url):
        """Extract image hash from Pinterest image URL"""
        # Pattern to match Pinterest image URLs and extract the hash path
        patterns = [
            # Match hex-based hash pattern: 13/85/b6/1385b6b23fafe4597dacd49933e715ce.jpg
            r'i\.pinimg\.com/(?:originals|1200x|736x|564x|474x|236x)/([a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]+\.(?:jpg|jpeg|png|webp))',
            # Match any other pattern: folder/folder/folder/filename.ext
            r'i\.pinimg\.com/(?:originals|1200x|736x|564x|474x|236x)/([^/]+/[^/]+/[^/]+/[^/]+\.(?:jpg|jpeg|png|webp))',
            # Fallback pattern for different structures
            r'i\.pinimg\.com/(?:originals|1200x|736x|564x|474x|236x)/(.+\.(?:jpg|jpeg|png|webp))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, img_url, re.IGNORECASE)
            if match:
                hash_path = match.group(1)
                print(f"{Fore.CYAN}DEBUG: Extracted hash: {hash_path} from {img_url}{Style.RESET_ALL}")
                return hash_path
        
        print(f"{Fore.YELLOW}DEBUG: No hash found in: {img_url}{Style.RESET_ALL}")
        return None

    def construct_image_urls(self, image_hash):
        """Construct image URLs for different quality levels"""
        if not image_hash:
            return []
        
        base_url = "https://i.pinimg.com"
        urls = []
        
        for quality in self.quality_levels:
            url = f"{base_url}/{quality}/{image_hash}"
            urls.append((quality, url))
        
        return urls

    def get_filename_from_hash(self, image_hash, quality):
        """Generate filename from image hash"""
        # Use the hash to create a unique filename
        hash_part = image_hash.replace('/', '_').replace('\\', '_')
        name_without_ext = hash_part.rsplit('.', 1)[0]
        ext = '.' + hash_part.rsplit('.', 1)[1] if '.' in hash_part else '.jpg'
        return f"{name_without_ext}_{quality}{ext}"

    def is_duplicate(self, filename):
        """Check if file already exists or is already downloaded"""
        filepath = self.output_dir / filename
        if filepath.exists():
            return True
        if filename in self.downloaded_files:
            return True
        return False

    def download_image(self, image_urls, image_hash, pbar_download):
        """Try to download image with quality fallback"""
        for quality, url in image_urls:
            try:
                filename = self.get_filename_from_hash(image_hash, quality)
                
                print(f"{Fore.CYAN}DEBUG: Trying to download {quality} quality: {url}{Style.RESET_ALL}")
                
                # Check for duplicates
                if self.is_duplicate(filename):
                    with self.lock:
                        self.duplicate_count += 1
                        pbar_download.set_description(
                            f"{Fore.GREEN}Downloaded: {self.downloaded_count} "
                            f"{Fore.YELLOW}Skipped: {self.skipped_count} "
                            f"{Fore.MAGENTA}Duplicates: {self.duplicate_count}{Style.RESET_ALL}"
                        )
                    print(f"{Fore.YELLOW}DEBUG: Duplicate found: {filename}{Style.RESET_ALL}")
                    return False, quality, None
                
                response = self.session.get(url, timeout=15, stream=True)
                print(f"{Fore.CYAN}DEBUG: Response status: {response.status_code} for {url}{Style.RESET_ALL}")
                
                if response.status_code == 200:
                    filepath = self.output_dir / filename
                    
                    # Download file
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # Check file size
                    file_size = filepath.stat().st_size
                    print(f"{Fore.GREEN}DEBUG: Successfully downloaded {filename} ({file_size} bytes) at {quality} quality{Style.RESET_ALL}")
                    
                    with self.lock:
                        self.downloaded_count += 1
                        self.downloaded_files.add(filename)
                        pbar_download.set_description(
                            f"{Fore.GREEN}Downloaded: {self.downloaded_count} "
                            f"{Fore.YELLOW}Skipped: {self.skipped_count} "
                            f"{Fore.MAGENTA}Duplicates: {self.duplicate_count}{Style.RESET_ALL}"
                        )
                        pbar_download.update(1)
                    
                    return True, quality, filepath
                else:
                    print(f"{Fore.YELLOW}DEBUG: Failed to download {quality} quality (HTTP {response.status_code}), trying next quality...{Style.RESET_ALL}")
                    
            except Exception as e:
                print(f"{Fore.YELLOW}DEBUG: Exception downloading {quality} quality: {str(e)}, trying next quality...{Style.RESET_ALL}")
                continue
        
        # All qualities failed
        print(f"{Fore.RED}DEBUG: All quality levels failed for hash: {image_hash}{Style.RESET_ALL}")
        with self.lock:
            self.skipped_count += 1
            pbar_download.set_description(
                f"{Fore.GREEN}Downloaded: {self.downloaded_count} "
                f"{Fore.YELLOW}Skipped: {self.skipped_count} "
                f"{Fore.MAGENTA}Duplicates: {self.duplicate_count}{Style.RESET_ALL}"
            )
        
        return False, None, None

    def load_urls_from_file(self, file_path):
        """Load Pinterest URLs from text file"""
        urls = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and line.startswith('https://www.pinterest.com/pin/'):
                        urls.append(line)
            return urls
        except Exception as e:
            print(f"{Fore.RED}Error reading file {file_path}: {e}{Style.RESET_ALL}")
            return []

    async def extract_images_and_download(self, pinterest_url, pbar_extract, pbar_download, images_per_url):
        """Scroll down Pinterest page, extract image URLs, and download them immediately"""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-features=VizDisplayCompositor',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--allow-running-insecure-content',
                        '--disable-extensions',
                        '--disable-plugins',
                        '--disable-images=false',  # Ensure images are loaded
                        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    ]
                )

                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none'
                    },
                    java_script_enabled=True,
                    ignore_https_errors=True
                )

                page = await context.new_page()
                page.set_default_timeout(20000)  # Increased to 20 seconds

                try:
                    # Try multiple loading strategies
                    print(f"\n{Fore.CYAN}🔄 Loading page: {pinterest_url}{Style.RESET_ALL}")
                    
                    # First attempt: networkidle
                    try:
                        await page.goto(pinterest_url, wait_until='networkidle', timeout=20000)
                        print(f"{Fore.GREEN}✓ Page loaded with networkidle{Style.RESET_ALL}")
                    except PlaywrightTimeoutError:
                        print(f"{Fore.YELLOW}⚠ networkidle failed, trying domcontentloaded...{Style.RESET_ALL}")
                        # Second attempt: domcontentloaded
                        try:
                            await page.goto(pinterest_url, wait_until='domcontentloaded', timeout=15000)
                            print(f"{Fore.GREEN}✓ Page loaded with domcontentloaded{Style.RESET_ALL}")
                        except PlaywrightTimeoutError:
                            print(f"{Fore.YELLOW}⚠ domcontentloaded failed, trying basic load...{Style.RESET_ALL}")
                            # Third attempt: basic load
                            await page.goto(pinterest_url, wait_until='load', timeout=10000)
                            print(f"{Fore.GREEN}✓ Page loaded with basic load{Style.RESET_ALL}")
                    
                    # Wait a bit for Pinterest to initialize
                    await asyncio.sleep(3)
                    
                    # Try to find Pinterest images with multiple selectors
                    pinterest_images_found = False
                    selectors_to_try = [
                        'img[src*="i.pinimg.com"]',
                        'img[data-src*="i.pinimg.com"]', 
                        'img[data-original*="i.pinimg.com"]',
                        'img',  # Fallback to any image
                    ]
                    
                    for selector in selectors_to_try:
                        try:
                            await page.wait_for_selector(selector, timeout=5000)
                            print(f"{Fore.GREEN}✓ Found images with selector: {selector}{Style.RESET_ALL}")
                            pinterest_images_found = True
                            break
                        except PlaywrightTimeoutError:
                            print(f"{Fore.YELLOW}⚠ No images found with selector: {selector}{Style.RESET_ALL}")
                            continue
                    
                    if not pinterest_images_found:
                        print(f"{Fore.YELLOW}⚠ No images found initially, but continuing to scroll...{Style.RESET_ALL}")
                        
                except PlaywrightTimeoutError:
                    print(f"\n{Fore.RED}✗ All page loading attempts failed: {pinterest_url}{Style.RESET_ALL}")
                    with self.lock:
                        self.skipped_pages.append(pinterest_url)
                    await browser.close()
                    return
                except Exception as e:
                    print(f"\n{Fore.RED}✗ Unexpected error loading page: {str(e)}{Style.RESET_ALL}")
                    with self.lock:
                        self.skipped_pages.append(pinterest_url)
                    await browser.close()
                    return

                all_image_urls = set()
                scrolls_done = 0
                no_new_content_count = 0
                downloaded_from_this_url = 0  # Track downloads from this specific URL
                
                print(f"{Fore.MAGENTA}🎯 Target: {images_per_url} images from this URL{Style.RESET_ALL}")

                while scrolls_done < self.max_scrolls and downloaded_from_this_url < images_per_url:
                    # Get current scroll position
                    previous_height = await page.evaluate('document.body.scrollHeight')
                    
                    # Scroll down in smaller increments for better loading
                    await page.evaluate('window.scrollBy(0, window.innerHeight)')
                    await asyncio.sleep(1)
                    
                    # Wait for new content to load
                    try:
                        await page.wait_for_function(
                            f'document.body.scrollHeight > {previous_height}',
                            timeout=3000
                        )
                    except PlaywrightTimeoutError:
                        # If no new content loads, try scrolling to absolute bottom
                        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                        await asyncio.sleep(2)

                    # Get all image elements with multiple strategies
                    img_elements = []
                    
                    # Try different selectors to find images
                    selectors_to_try = [
                        'img[src*="i.pinimg.com"]',
                        'img[data-src*="i.pinimg.com"]',
                        'img[data-original*="i.pinimg.com"]',
                        'img'  # Fallback
                    ]
                    
                    for selector in selectors_to_try:
                        try:
                            elements = await page.query_selector_all(selector)
                            if elements:
                                img_elements.extend(elements)
                                print(f"{Fore.CYAN}Found {len(elements)} images with selector: {selector}{Style.RESET_ALL}")
                                break
                        except Exception as e:
                            print(f"{Fore.YELLOW}Error with selector {selector}: {str(e)}{Style.RESET_ALL}")
                            continue
                    
                    if not img_elements:
                        print(f"{Fore.YELLOW}No images found on this scroll, trying to scroll more...{Style.RESET_ALL}")
                        continue
                        
                    print(f"{Fore.CYAN}Processing {len(img_elements)} total image elements{Style.RESET_ALL}")
                    
                    new_images_found = 0
                    for i, img in enumerate(img_elements):
                        try:
                            # Try different attributes to get image URL
                            src = None
                            for attr in ['src', 'data-src', 'data-original']:
                                src = await img.get_attribute(attr)
                                if src and "i.pinimg.com" in src:
                                    break
                            
                            if src and "i.pinimg.com" in src and not src.lower().endswith('.gif'):
                                print(f"{Fore.CYAN}DEBUG: Processing image {i+1}: {src}{Style.RESET_ALL}")
                                image_hash = self.extract_hash_from_url(src)
                                if image_hash and image_hash not in all_image_urls:
                                    # Check if we've reached the limit for this URL
                                    if downloaded_from_this_url >= images_per_url:
                                        print(f"\n{Fore.GREEN}✓ Reached target of {images_per_url} images for this URL{Style.RESET_ALL}")
                                        break
                                    
                                    all_image_urls.add(image_hash)
                                    new_images_found += 1
                                    image_urls = self.construct_image_urls(image_hash)
                                    success, quality, filepath = self.download_image(image_urls, image_hash, pbar_download)
                                    
                                    # If download was successful, increment our local counter
                                    if success:
                                        downloaded_from_this_url += 1
                                        
                                    # Check again after download attempt
                                    if downloaded_from_this_url >= images_per_url:
                                        print(f"\n{Fore.GREEN}✓ Reached target of {images_per_url} images for this URL{Style.RESET_ALL}")
                                        break
                                elif image_hash:
                                    print(f"{Fore.YELLOW}DEBUG: Already processed this image hash{Style.RESET_ALL}")
                            else:
                                if not src:
                                    print(f"{Fore.YELLOW}DEBUG: No src found for image {i+1}{Style.RESET_ALL}")
                                elif "i.pinimg.com" not in src:
                                    print(f"{Fore.YELLOW}DEBUG: Non-Pinterest image: {src[:100]}...{Style.RESET_ALL}")
                        except Exception as e:
                            print(f"{Fore.RED}DEBUG: Error processing image {i+1}: {str(e)}{Style.RESET_ALL}")
                            continue
                            
                    # Break the inner for loop if we reached the target
                    if downloaded_from_this_url >= images_per_url:
                        break

                    # Update progress tracking
                    current_image_count = len(all_image_urls)
                    if new_images_found == 0:
                        no_new_content_count += 1
                        if no_new_content_count >= 5:  # Increased patience for slow loading
                            print(f"\n{Fore.YELLOW}No new images found after 5 attempts, stopping...{Style.RESET_ALL}")
                            break
                    else:
                        no_new_content_count = 0

                    scrolls_done += 1
                    pbar_extract.set_description(
                        f"{Fore.BLUE}Scrolling{Style.RESET_ALL} | {Fore.GREEN}Downloaded: {downloaded_from_this_url}/{images_per_url}{Style.RESET_ALL} | {Fore.CYAN}Scroll: {scrolls_done}/{self.max_scrolls}{Style.RESET_ALL} | {Fore.MAGENTA}New: {new_images_found}{Style.RESET_ALL}"
                    )

                    if downloaded_from_this_url >= images_per_url:
                        print(f"\n{Fore.GREEN}✓ Reached target of {images_per_url} images for this URL, moving to next URL{Style.RESET_ALL}")
                        break
                    
                    # Small delay between scrolls to be respectful
                    await asyncio.sleep(0.5)

                await browser.close()
                print(f"{Fore.GREEN}📊 Extracted {len(all_image_urls)} images from this URL{Style.RESET_ALL}")
                
            except Exception as e:
                print(f"{Fore.RED}ERROR: {str(e)}{Style.RESET_ALL}")
                with self.lock:
                    self.skipped_pages.append(pinterest_url)

    async def extract_images_from_urls(self, urls, pbar_extract, pbar_download):
        """Extract images from all URLs and download them immediately"""
        # Calculate how many images to download per URL
        total_urls = len(urls)
        images_per_url = max(1, self.max_downloads // total_urls)  # At least 1 image per URL
        remaining_images = self.max_downloads % total_urls  # Extra images to distribute
        
        print(f"\n{Fore.CYAN}📊 Distribution Plan:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Total URLs: {total_urls}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Base images per URL: {images_per_url}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Extra images for first {remaining_images} URLs: +1 each{Style.RESET_ALL}")
        print()
        
        for i, url in enumerate(urls):
            # First few URLs get an extra image if there are remainders
            current_images_per_url = images_per_url + (1 if i < remaining_images else 0)
            
            print(f"\n{Fore.MAGENTA}Processing URL {i+1}/{total_urls} (target: {current_images_per_url} images):{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}{url}{Style.RESET_ALL}")
            
            await self.extract_images_and_download(url, pbar_extract, pbar_download, current_images_per_url)
            pbar_extract.update(1)

    def process_urls(self, urls):
        """Main processing function"""
        if not urls:
            print(f"{Fore.RED}No valid URLs found!{Style.RESET_ALL}")
            return
        
        total_urls = len(urls)
        
        print(f"{Fore.CYAN}Processing {total_urls} Pinterest URLs...{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Max downloads: {self.max_downloads}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Max scrolls per page: {self.max_scrolls}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Parallel workers: {self.max_workers}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Output directory: {self.output_dir}{Style.RESET_ALL}")
        print()
        
        # Phase 1: Extract all image URLs by scrolling
        print(f"{Fore.MAGENTA}Phase 1: Scrolling pages and extracting images...{Style.RESET_ALL}")
        
        with tqdm(total=total_urls, 
                 desc=f"{Fore.BLUE}Extracting{Style.RESET_ALL}", 
                 bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]',
                 colour='blue') as pbar_extract, \
             tqdm(total=self.max_downloads, 
                 desc=f"{Fore.GREEN}Downloaded: 0 {Fore.YELLOW}Skipped: 0 {Fore.MAGENTA}Duplicates: 0{Style.RESET_ALL}",
                 bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]',
                 colour='green') as pbar_download:

            # Run async extraction and download
            asyncio.run(self.extract_images_from_urls(urls, pbar_extract, pbar_download))
        
        # Check for skipped pages
        if self.skipped_pages:
            print(f"\n{Fore.RED}Skipped pages (timeout/error):{Style.RESET_ALL}")
            for skipped_url in self.skipped_pages:
                print(f"  {Fore.YELLOW}- {skipped_url}{Style.RESET_ALL}")
        
        # Final statistics
        print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✓ Successfully downloaded: {self.downloaded_count}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}⚠ Skipped (download failed): {self.skipped_count}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}⚠ Duplicates avoided: {self.duplicate_count}{Style.RESET_ALL}")
        print(f"{Fore.RED}✗ Pages skipped (timeout/error): {len(self.skipped_pages)}{Style.RESET_ALL}")
        
        if self.skipped_pages:
            print(f"\n{Fore.RED}Skipped URLs:{Style.RESET_ALL}")
            for skipped_url in self.skipped_pages:
                print(f"  {Fore.YELLOW}- {skipped_url}{Style.RESET_ALL}")
        
        print(f"\n{Fore.CYAN}📁 Output directory: {self.output_dir.absolute()}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")


def main():
    parser = argparse.ArgumentParser(description='Pinterest Image Downloader with Playwright')
    parser.add_argument('input_file', help='Path to text file containing Pinterest URLs')
    parser.add_argument('-m', '--max-downloads', type=int, default=50, 
                       help='Maximum number of images to download (default: 50)')
    parser.add_argument('-w', '--workers', type=int, default=4,
                       help='Number of parallel download workers (default: 4)')
    parser.add_argument('-o', '--output', default='temp',
                       help='Output directory (default: temp)')
    parser.add_argument('-s', '--scrolls', type=int, default=100,
                       help='Maximum scrolls per page (default: 100)')
    
    args = parser.parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.input_file):
        print(f"{Fore.RED}Error: Input file '{args.input_file}' not found!{Style.RESET_ALL}")
        return
    
    # Create downloader instance
    downloader = PinterestPlaywrightDownloader(
        max_downloads=args.max_downloads,
        max_workers=args.workers,
        output_dir=args.output,
        max_scrolls=args.scrolls
    )
    
    # Load URLs and start processing
    urls = downloader.load_urls_from_file(args.input_file)
    if urls:
        print(f"{Fore.CYAN}Loaded {len(urls)} URLs from {args.input_file}{Style.RESET_ALL}")
        downloader.process_urls(urls)
    else:
        print(f"{Fore.RED}No valid Pinterest URLs found in {args.input_file}!{Style.RESET_ALL}")


if __name__ == "__main__":
    main()