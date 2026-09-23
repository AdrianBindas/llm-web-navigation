from page_extractor import OutputConfig, PageExtractor

WEBSITE_URL = "https://tiktok.com/"
# WEBSITE_URL = "https://www.bilibili.com/"


def main():
    extractor = PageExtractor(output_config=OutputConfig(stdout=False))
    result = extractor.run(WEBSITE_URL)
    print(f"Found {len(result.boxes)} bounding boxes.")


if __name__ == "__main__":
    main()
