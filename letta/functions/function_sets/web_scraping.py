from typing import List, Optional


async def crw_scrape(
    url: str,
    formats: Optional[List[str]] = None,
    only_main_content: bool = True,
    css_selector: Optional[str] = None,
) -> str:
    """
    Scrape a single web page and return its content using CRW (open-source web scraper).

    Converts web pages to clean markdown, HTML, or plain text. Useful for extracting
    article content, documentation pages, or any web content for analysis.

    Examples:
        crw_scrape("https://example.com")
        crw_scrape("https://example.com", formats=["markdown", "links"])
        crw_scrape("https://news.ycombinator.com", css_selector="td.title", only_main_content=False)

    Args:
        url (str): The URL to scrape (http/https only).
        formats (Optional[List[str]]): Output formats to return. Options: "markdown", "html",
            "rawHtml", "plainText", "links". Defaults to ["markdown"].
        only_main_content (bool): If True, strips navigation, footer, and sidebar.
            Defaults to True.
        css_selector (Optional[str]): CSS selector to extract only matching elements.
            When provided, only the matching HTML is converted.

    Returns:
        str: A JSON-encoded string containing the scraped content and metadata.
    """
    raise NotImplementedError("This is only available on the latest agent architecture. Please contact the Letta team.")


async def crw_crawl(
    url: str,
    max_depth: int = 2,
    max_pages: int = 100,
    formats: Optional[List[str]] = None,
    only_main_content: bool = True,
) -> str:
    """
    Crawl a website starting from a URL, following links up to a specified depth.

    Starts an asynchronous crawl job that discovers and scrapes multiple pages.
    Returns a job ID that can be used to check the crawl status and retrieve results.

    Examples:
        crw_crawl("https://docs.example.com")
        crw_crawl("https://example.com", max_depth=3, max_pages=50)

    Args:
        url (str): The starting URL to crawl (http/https only).
        max_depth (int): Maximum link-follow depth from the starting URL. Defaults to 2.
        max_pages (int): Maximum number of pages to scrape. Defaults to 100.
        formats (Optional[List[str]]): Output formats for each page. Options: "markdown",
            "html", "rawHtml", "plainText", "links". Defaults to ["markdown"].
        only_main_content (bool): If True, strips navigation, footer, and sidebar
            from each page. Defaults to True.

    Returns:
        str: A JSON-encoded string. If the crawl completes quickly, returns the crawled data.
            Otherwise, returns a job ID and status for polling.
    """
    raise NotImplementedError("This is only available on the latest agent architecture. Please contact the Letta team.")


async def crw_map(
    url: str,
    max_depth: int = 2,
    use_sitemap: bool = True,
) -> str:
    """
    Discover all URLs on a website without scraping their content.

    Useful for understanding site structure, finding specific pages, or planning
    a targeted crawl. Reads sitemap.xml when available for comprehensive discovery.

    Examples:
        crw_map("https://example.com")
        crw_map("https://docs.example.com", max_depth=3, use_sitemap=True)

    Args:
        url (str): The URL to discover links from (http/https only).
        max_depth (int): Maximum discovery depth. Defaults to 2.
        use_sitemap (bool): Whether to also read sitemap.xml for URL discovery.
            Defaults to True.

    Returns:
        str: A JSON-encoded string containing the list of discovered URLs.
    """
    raise NotImplementedError("This is only available on the latest agent architecture. Please contact the Letta team.")
