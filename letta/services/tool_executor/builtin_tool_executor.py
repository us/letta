import asyncio
import json
from typing import Any, Dict, List, Literal, Optional

from letta.log import get_logger
from letta.otel.tracing import trace_method
from letta.schemas.agent import AgentState
from letta.schemas.sandbox_config import SandboxConfig
from letta.schemas.tool import Tool
from letta.schemas.tool_execution_result import ToolExecutionResult
from letta.schemas.user import User
from letta.services.tool_executor.tool_executor_base import ToolExecutor
from letta.settings import tool_settings

logger = get_logger(__name__)


class LettaBuiltinToolExecutor(ToolExecutor):
    """Executor for built in Letta tools."""

    @trace_method
    async def execute(
        self,
        function_name: str,
        function_args: dict,
        tool: Tool,
        actor: User,
        agent_state: Optional[AgentState] = None,
        sandbox_config: Optional[SandboxConfig] = None,
        sandbox_env_vars: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionResult:
        function_map = {
            "run_code": self.run_code,
            "run_code_with_tools": self.run_code_with_tools,
            "web_search": self.web_search,
            "fetch_webpage": self.fetch_webpage,
            "crw_scrape": self.crw_scrape,
            "crw_crawl": self.crw_crawl,
            "crw_map": self.crw_map,
        }

        if function_name not in function_map:
            raise ValueError(f"Unknown function: {function_name}")

        # Execute the appropriate function
        function_args_copy = function_args.copy()  # Make a copy to avoid modifying the original
        function_response = await function_map[function_name](agent_state=agent_state, **function_args_copy)

        return ToolExecutionResult(
            status="success",
            func_return=function_response,
            agent_state=agent_state,
        )

    async def run_code_with_tools(self, agent_state: "AgentState", code: str) -> ToolExecutionResult:
        from e2b_code_interpreter import AsyncSandbox

        from letta.utils import get_friendly_error_msg

        if tool_settings.e2b_api_key is None:
            raise ValueError("E2B_API_KEY is not set")

        env = {"LETTA_AGENT_ID": agent_state.id}
        env.update(agent_state.get_agent_env_vars_as_dict())

        # Create the sandbox, using template if configured (similar to tool_execution_sandbox.py)
        if tool_settings.e2b_sandbox_template_id:
            sbx = await AsyncSandbox.create(tool_settings.e2b_sandbox_template_id, api_key=tool_settings.e2b_api_key, envs=env)
        else:
            sbx = await AsyncSandbox.create(api_key=tool_settings.e2b_api_key, envs=env)

        tool_source_code = ""
        lines = []

        # initialize the letta client
        lines.extend(
            [
                "# Initialize Letta client for tool execution",
                "import os",
                "from letta_client import Letta",
                "client = None",
                "if os.getenv('LETTA_API_KEY'):",
                "    # Check letta_client version to use correct parameter name",
                "    from packaging import version as pkg_version",
                "    import letta_client as lc_module",
                "    lc_version = pkg_version.parse(lc_module.__version__)",
                "    if lc_version < pkg_version.parse('1.0.0'):",
                "        client = Letta(",
                "            token=os.getenv('LETTA_API_KEY')",
                "        )",
                "    else:",
                "        client = Letta(",
                "            api_key=os.getenv('LETTA_API_KEY')",
                "        )",
            ]
        )
        tool_source_code = "\n".join(lines) + "\n"
        # Inject source code from agent's tools to enable programmatic tool calling
        # This allows Claude to compose tools in a single code execution, e.g.:
        #   run_code("result = add(multiply(4, 5), 6)")
        from letta.schemas.enums import ToolType

        if agent_state and agent_state.tools:
            for tool in agent_state.tools:
                if tool.tool_type == ToolType.CUSTOM and tool.source_code:
                    # simply append the source code of the tool
                    # TODO: can get rid of this option
                    tool_source_code += tool.source_code + "\n\n"
                else:
                    # invoke the tool through the client
                    # raises an error if LETTA_API_KEY or other envs not set
                    tool_lines = [
                        f"def {tool.name}(**kwargs):",
                        "    if not os.getenv('LETTA_API_KEY'):",
                        "        raise ValueError('LETTA_API_KEY is not set')",
                        "    if not os.getenv('LETTA_AGENT_ID'):",
                        "        raise ValueError('LETTA_AGENT_ID is not set')",
                        f"    result = client.agents.tools.run(agent_id=os.getenv('LETTA_AGENT_ID'), tool_name='{tool.name}', args=kwargs)",
                        "    if result.status == 'success':",
                        "        return result.func_return",
                        "    else:",
                        "        raise ValueError(result.stderr)",
                    ]
                    tool_source_code += "\n".join(tool_lines) + "\n\n"

        params = {"code": tool_source_code + code}

        execution = await sbx.run_code(**params)

        # Parse results similar to e2b_sandbox.py
        if execution.results:
            func_return = execution.results[0].text if hasattr(execution.results[0], "text") else str(execution.results[0])
        elif execution.error:
            func_return = get_friendly_error_msg(
                function_name="run_code_with_tools", exception_name=execution.error.name, exception_message=execution.error.value
            )
            execution.logs.stderr.append(execution.error.traceback)
        else:
            func_return = None

        return json.dumps(
            {
                "status": "error" if execution.error else "success",
                "func_return": func_return,
                "stdout": execution.logs.stdout,
                "stderr": execution.logs.stderr,
            },
            ensure_ascii=False,
        )

    async def run_code(self, agent_state: "AgentState", code: str, language: Literal["python", "js", "ts", "r", "java"]) -> str:
        from e2b_code_interpreter import AsyncSandbox

        if tool_settings.e2b_api_key is None:
            raise ValueError("E2B_API_KEY is not set")

        # Create the sandbox, using template if configured (similar to tool_execution_sandbox.py)
        if tool_settings.e2b_sandbox_template_id:
            sbx = await AsyncSandbox.create(tool_settings.e2b_sandbox_template_id, api_key=tool_settings.e2b_api_key)
        else:
            sbx = await AsyncSandbox.create(api_key=tool_settings.e2b_api_key)

        # Inject source code from agent's tools to enable programmatic tool calling
        # This allows Claude to compose tools in a single code execution, e.g.:
        #   run_code_with_tools("result = add(multiply(4, 5), 6)")
        if language == "python" and agent_state and agent_state.tools:
            tool_source_code = ""
            for tool in agent_state.tools:
                if tool.source_code:
                    tool_source_code += tool.source_code + "\n\n"
            if tool_source_code:
                code = tool_source_code + code

        params = {"code": code}
        if language != "python":
            # Leave empty for python
            params["language"] = language

        res = self._llm_friendly_result(await sbx.run_code(**params))
        return json.dumps(res, ensure_ascii=False)

    def _llm_friendly_result(self, res):
        out = {
            "results": [r.text if hasattr(r, "text") else str(r) for r in res.results],
            "logs": {
                "stdout": getattr(res.logs, "stdout", []),
                "stderr": getattr(res.logs, "stderr", []),
            },
        }
        err = getattr(res, "error", None)
        if err is not None:
            out["error"] = err
        return out

    @trace_method
    async def web_search(
        self,
        agent_state: "AgentState",
        query: str,
        num_results: int = 10,
        category: Optional[
            Literal["company", "research paper", "news", "pdf", "github", "tweet", "personal site", "linkedin profile", "financial report"]
        ] = None,
        include_text: bool = False,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        start_published_date: Optional[str] = None,
        end_published_date: Optional[str] = None,
        user_location: Optional[str] = None,
    ) -> str:
        """
        Search the web using Exa's AI-powered search engine and retrieve relevant content.

        Args:
            query: The search query to find relevant web content
            num_results: Number of results to return (1-100)
            category: Focus search on specific content types
            include_text: Whether to retrieve full page content (default: False, only returns summary and highlights)
            include_domains: List of domains to include in search results
            exclude_domains: List of domains to exclude from search results
            start_published_date: Only return content published after this date (ISO format)
            end_published_date: Only return content published before this date (ISO format)
            user_location: Two-letter country code for localized results

        Returns:
            JSON-encoded string containing search results
        """
        try:
            from exa_py import Exa
        except ImportError:
            raise ImportError("exa-py is not installed in the tool execution environment")

        if not query.strip():
            return json.dumps({"error": "Query cannot be empty", "query": query})

        # Get EXA API key from agent environment or tool settings
        agent_state_tool_env_vars = agent_state.get_agent_env_vars_as_dict()
        exa_api_key = agent_state_tool_env_vars.get("EXA_API_KEY") or tool_settings.exa_api_key
        if not exa_api_key:
            raise ValueError("EXA_API_KEY is not set in environment or on agent_state tool execution environment variables.")

        logger.info(f"[DEBUG] Starting Exa web search for query: '{query}' with {num_results} results")

        # Build search parameters
        search_params = {
            "query": query,
            "num_results": min(max(num_results, 1), 100),  # Clamp between 1-100
            "type": "auto",  # Always use auto search type
        }

        # Add optional parameters if provided
        if category:
            search_params["category"] = category
        if include_domains:
            search_params["include_domains"] = include_domains
        if exclude_domains:
            search_params["exclude_domains"] = exclude_domains
        if start_published_date:
            search_params["start_published_date"] = start_published_date
        if end_published_date:
            search_params["end_published_date"] = end_published_date
        if user_location:
            search_params["user_location"] = user_location

        # Configure contents retrieval
        contents_params = {
            "text": include_text,
            "highlights": {"num_sentences": 2, "highlights_per_url": 3, "query": query},
            "summary": {"query": f"Summarize the key information from this content related to: {query}"},
        }

        def _sync_exa_search():
            """Synchronous Exa API call to run in thread pool."""
            exa = Exa(api_key=exa_api_key)
            return exa.search_and_contents(**search_params, **contents_params)

        try:
            # Perform search with content retrieval in thread pool to avoid blocking event loop
            logger.info(f"[DEBUG] Making async Exa API call with params: {search_params}")
            result = await asyncio.to_thread(_sync_exa_search)

            # Format results
            formatted_results = []
            for res in result.results:
                formatted_result = {
                    "title": res.title,
                    "url": res.url,
                    "published_date": res.published_date,
                    "author": res.author,
                }

                # Add content if requested
                if include_text and hasattr(res, "text") and res.text:
                    formatted_result["text"] = res.text

                # Add highlights if available
                if hasattr(res, "highlights") and res.highlights:
                    formatted_result["highlights"] = res.highlights

                # Add summary if available
                if hasattr(res, "summary") and res.summary:
                    formatted_result["summary"] = res.summary

                formatted_results.append(formatted_result)

            response = {"query": query, "results": formatted_results}

            logger.info(f"[DEBUG] Exa search completed successfully with {len(formatted_results)} results")
            return json.dumps(response, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.info(f"Exa search failed for query '{query}': {str(e)}")
            return json.dumps({"query": query, "error": f"Search failed: {str(e)}"})

    async def fetch_webpage(self, agent_state: "AgentState", url: str) -> str:
        """
        Fetch a webpage and convert it to markdown/text format using Exa API (if available) or trafilatura/readability.

        Args:
            url: The URL of the webpage to fetch and convert

        Returns:
            String containing the webpage content in markdown/text format
        """
        import asyncio
        from urllib.parse import urlparse

        import html2text
        import requests
        from readability import Document
        from trafilatura import extract, fetch_url

        # Validate URL scheme - only HTTP and HTTPS are supported
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() not in ("http", "https"):
            raise ValueError(
                f"Invalid URL scheme '{parsed_url.scheme}'. Only 'http' and 'https' URLs are supported. "
                f"Local file paths (file://) and other protocols cannot be fetched."
            )

        # Try exa first
        try:
            from exa_py import Exa

            agent_state_tool_env_vars = agent_state.get_agent_env_vars_as_dict()
            exa_api_key = agent_state_tool_env_vars.get("EXA_API_KEY") or tool_settings.exa_api_key
            if exa_api_key:
                logger.info(f"[DEBUG] Starting Exa fetch content for url: '{url}'")
                exa = Exa(api_key=exa_api_key)

                results = await asyncio.to_thread(
                    lambda: exa.get_contents(
                        [url],
                        text=True,
                    ).results
                )

                if len(results) > 0:
                    result = results[0]
                    return json.dumps(
                        {
                            "title": result.title,
                            "published_date": result.published_date,
                            "author": result.author,
                            "text": result.text,
                        }
                    )
                else:
                    logger.info(f"[DEBUG] Exa did not return content for '{url}', falling back to local fetch.")
            else:
                logger.info("[DEBUG] No Exa key available, falling back to local fetch.")
        except ImportError:
            logger.info("[DEBUG] Exa pip package unavailable, falling back to local fetch.")
            pass

        try:
            # single thread pool call for the entire trafilatura pipeline
            def trafilatura_pipeline():
                downloaded = fetch_url(url)  # fetch_url doesn't accept timeout parameter
                if downloaded:
                    md = extract(downloaded, output_format="markdown")
                    return md

            md = await asyncio.to_thread(trafilatura_pipeline)
            if md:
                return md

            # single thread pool call for the entire fallback pipeline
            def readability_pipeline():
                response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; LettaBot/1.0)"})
                response.raise_for_status()

                doc = Document(response.text)
                clean_html = doc.summary(html_partial=True)
                return html2text.html2text(clean_html)

            return await asyncio.to_thread(readability_pipeline)

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching webpage: {str(e)}")
        except Exception as e:
            raise Exception(f"Unexpected error: {str(e)}")

    def _get_crw_config(self, agent_state: "AgentState") -> tuple:
        """Get CRW base URL and API key from agent env vars or tool settings.

        Returns:
            tuple: (base_url, headers) for CRW API requests.
        """
        agent_env_vars = agent_state.get_agent_env_vars_as_dict()
        crw_base_url = agent_env_vars.get("CRW_BASE_URL") or tool_settings.crw_base_url
        crw_api_key = agent_env_vars.get("CRW_API_KEY") or tool_settings.crw_api_key

        if not crw_base_url:
            raise ValueError(
                "CRW_BASE_URL is not set. Configure it in environment variables, tool settings, "
                "or agent environment variables. CRW is an open-source web scraper: https://github.com/crw-org/crw"
            )

        # Strip trailing slash
        crw_base_url = crw_base_url.rstrip("/")

        headers = {"Content-Type": "application/json"}
        if crw_api_key:
            headers["Authorization"] = f"Bearer {crw_api_key}"

        return crw_base_url, headers

    @trace_method
    async def crw_scrape(
        self,
        agent_state: "AgentState",
        url: str,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        css_selector: Optional[str] = None,
    ) -> str:
        """
        Scrape a single web page using CRW.

        Args:
            agent_state: The current agent state.
            url: The URL to scrape.
            formats: Output formats (e.g., ["markdown", "html", "links"]).
            only_main_content: Strip navigation, footer, sidebar.
            css_selector: CSS selector to extract only matching elements.

        Returns:
            JSON-encoded string with scraped content and metadata.
        """
        import aiohttp

        crw_base_url, headers = self._get_crw_config(agent_state)

        payload = {
            "url": url,
            "onlyMainContent": only_main_content,
        }
        if formats:
            payload["formats"] = formats
        if css_selector:
            payload["cssSelector"] = css_selector

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{crw_base_url}/v1/scrape",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    result = await resp.json()

                    if resp.status != 200:
                        error_msg = result.get("error", f"CRW scrape failed with status {resp.status}")
                        return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

                    return json.dumps(result, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"CRW scrape failed for URL '{url}': {str(e)}")
            return json.dumps({"success": False, "error": f"CRW scrape failed: {str(e)}"}, ensure_ascii=False)

    @trace_method
    async def crw_crawl(
        self,
        agent_state: "AgentState",
        url: str,
        max_depth: int = 2,
        max_pages: int = 100,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
    ) -> str:
        """
        Crawl a website starting from a URL using CRW.

        Starts a crawl job and polls for completion. If the crawl completes within
        the timeout, returns the full results. Otherwise, returns the job ID and status.

        Args:
            agent_state: The current agent state.
            url: The starting URL to crawl.
            max_depth: Maximum link-follow depth.
            max_pages: Maximum number of pages to scrape.
            formats: Output formats for each page.
            only_main_content: Strip boilerplate from each page.

        Returns:
            JSON-encoded string with crawl results or job status.
        """
        import aiohttp

        crw_base_url, headers = self._get_crw_config(agent_state)

        payload = {
            "url": url,
            "maxDepth": max_depth,
            "maxPages": max_pages,
            "onlyMainContent": only_main_content,
        }
        if formats:
            payload["formats"] = formats

        try:
            async with aiohttp.ClientSession() as session:
                # Start the crawl job
                async with session.post(
                    f"{crw_base_url}/v1/crawl",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    start_result = await resp.json()

                    if resp.status != 200 or not start_result.get("success"):
                        error_msg = start_result.get("error", f"CRW crawl failed with status {resp.status}")
                        return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

                    job_id = start_result.get("id")
                    if not job_id:
                        return json.dumps({"success": False, "error": "No job ID returned from CRW"}, ensure_ascii=False)

                # Poll for completion (up to 60 seconds)
                max_polls = 30
                for _ in range(max_polls):
                    await asyncio.sleep(2)
                    async with session.get(
                        f"{crw_base_url}/v1/crawl/{job_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as status_resp:
                        status_result = await status_resp.json()
                        status = status_result.get("status", "")

                        if status == "completed":
                            return json.dumps(status_result, indent=2, ensure_ascii=False)
                        elif status == "failed":
                            return json.dumps(
                                {"success": False, "error": "Crawl job failed", "details": status_result},
                                ensure_ascii=False,
                            )

                # If still running after timeout, return the job info
                return json.dumps(
                    {
                        "success": True,
                        "status": "still_running",
                        "job_id": job_id,
                        "message": f"Crawl is still in progress. Check status at GET {crw_base_url}/v1/crawl/{job_id}",
                    },
                    ensure_ascii=False,
                )

        except Exception as e:
            logger.error(f"CRW crawl failed for URL '{url}': {str(e)}")
            return json.dumps({"success": False, "error": f"CRW crawl failed: {str(e)}"}, ensure_ascii=False)

    @trace_method
    async def crw_map(
        self,
        agent_state: "AgentState",
        url: str,
        max_depth: int = 2,
        use_sitemap: bool = True,
    ) -> str:
        """
        Discover all URLs on a website using CRW.

        Args:
            agent_state: The current agent state.
            url: The URL to discover links from.
            max_depth: Maximum discovery depth.
            use_sitemap: Whether to read sitemap.xml.

        Returns:
            JSON-encoded string with discovered URLs.
        """
        import aiohttp

        crw_base_url, headers = self._get_crw_config(agent_state)

        payload = {
            "url": url,
            "maxDepth": max_depth,
            "useSitemap": use_sitemap,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{crw_base_url}/v1/map",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    result = await resp.json()

                    if resp.status != 200:
                        error_msg = result.get("error", f"CRW map failed with status {resp.status}")
                        return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

                    return json.dumps(result, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"CRW map failed for URL '{url}': {str(e)}")
            return json.dumps({"success": False, "error": f"CRW map failed: {str(e)}"}, ensure_ascii=False)
