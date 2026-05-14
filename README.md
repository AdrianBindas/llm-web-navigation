# Browser Automation with Natural Language Instructions Utilizing Multimodal Methods
Diploma thesis repository

## Planning
- ~~End of 2025 - Thesis assignment formulated and submitted~~
- ~~Spring 2026 - Exploration of existing approaches~~
- ~~April 2026 - Writing down introduction and specification of methodology~~
- ~~May 2026 - Gathering few online website samples~~
- May 2026 - Implementation of a "proof of concept" Candidate Generation
- June 2026 - Implementation of a "proof of concept" Action Prediction (text-based approach first)
- July 2026 - Data gathering, extending existing bechmark
- August - September 2026 - Implementation of full method
- Winter 2026 - Evaluation of implemented method, comparison with existing methods
- Spring 2027 - Writing and finishing paper

## Technology Stack
### General
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) Python package manager in Rust
- [MatPlotLib](https://matplotlib.org/stable/users/index) Visualization and plotting 

### Candidate Generation
- [BeautifulSoup4](https://pypi.org/project/beautifulsoup4/) Python library for manipulating HTML with backend in C
- [Playwright](https://playwright.dev/) Web Automation library
- [Ultralytics (YOLO)](https://docs.ultralytics.com/usage/python/) Inference and training of YOLO models
- [NLTK](https://tedboy.github.io/nlps/nltk_intro.html) Text processing, classification and various NLP tasks

### Action Prediction
- [PyTorch](https://docs.pytorch.org/docs/2.11/index.html) Deep learning library for tensor computation
- [Transformers](https://github.com/huggingface/transformers) Machine learning high-level framework maintained by HuggingFace, provides abstractions for model inference, training, finetuning...
- [vLLM](https://docs.vllm.ai/en/latest/usage/) Framework for LLM inference and serving

## Thesis Assignment
Automated interactions with web pages is a common process crucial for tasks such as testing and web scraping implemented by frameworks (such as Selenium, Playwright, Puppeteer). However it suffers from low reliability, poor robustness to website structure changes and high dependency on platform and target website. This thesis aims to **propose and evaluate novel improvements in this field combining Large Language Models (LLM), text processing and computer vision**.

First, recent **advancements in this field are surveyed**. Promising **methods are evaluated on a dataset** consisting of web pages of diverse design patterns, use-cases and characteristics. Novel **method is proposed and implemented**, offering a robust approach to interact with a website based on the natural language instructions. The method scrapes data from websites and processes text structure in a combination with visual representation to construct a view that efficiently conveys information about website structure. This combined view is processed by a model (e.g., LLM) that decides on a specific interaction (e.g., click or key press) and appropriate element. Advancements in speed of execution and cost efficiency are valuable to facilitate the application of this process in real life scenarios.

## Thesis Goals
The goals of the thesis include (but are not limited to):
- Create a dataset of web pages that includes hierarchical text structure (HTML and DOM) along with visual representation (screenshot). Dataset includes variety of web pages, ranging from static web pages to dynamic such as e-commerce and social media 
- Survey approaches for browser automation utilizing modern methods (e.g., Large Language Models, OCR, multimodal models) and evaluate them on the dataset.
- Propose a new method that combines text structure and visual representation of the website to allow for more robust and reliable automated interaction. The approach supports natural language instructions and optimizes speed of execution and cost efficiency to facilitate its application.
- Evaluate the method on the created dataset and compare it to existing methods.