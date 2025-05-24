"""
(c) 2017 DigitalOcean

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

This module provides the core query functionality for interacting with the NetBox API.
It handles HTTP requests, pagination, error handling, and response processing.
"""

import concurrent.futures as cf
import json

from packaging import version


def calc_pages(limit, count):
    """Calculate number of pages required for full results set.
    
    Args:
        limit (int): Number of items per page
        count (int): Total number of items
        
    Returns:
        int: Number of pages needed to display all items
        
    Example:
        >>> calc_pages(10, 25)  # Returns 3 pages for 25 items with 10 per page
    """
    return int(count / limit) + (limit % count > 0)


class RequestError(Exception):
    """Exception raised when a request to the NetBox API fails.
    
    This exception provides detailed information about the failed request,
    including the original request object, status code, and error message.
    
    Attributes:
        message (str): Human-readable error message
        req: The original requests object
        request_body: The body of the failed request
        base (str): The base URL of the request
        error (str): The error text returned by the API
    """

    def __init__(self, req):
        if req.status_code == 404:
            self.message = "The requested url: {} could not be found.".format(req.url)
        else:
            try:
                self.message = "The request failed with code {} {}: {}".format(
                    req.status_code, req.reason, req.json()
                )
            except ValueError:
                self.message = (
                    "The request failed with code {} {} but more specific "
                    "details were not returned in json. Check the NetBox Logs "
                    "or investigate this exception's error attribute.".format(
                        req.status_code, req.reason
                    )
                )

        super().__init__(self.message)
        self.req = req
        self.request_body = req.request.body
        self.base = req.url
        self.error = req.text

    def __str__(self):
        return self.message


class AllocationError(Exception):
    """Exception raised when IP or prefix allocation fails due to no available space.
    
    This exception is specifically used when NetBox returns a 409 Conflict status
    for available-ips or available-prefixes endpoints.
    
    Attributes:
        req: The original requests object
        request_body: The body of the failed request
        base (str): The base URL of the request
        error (str): Fixed error message about allocation failure
    """

    def __init__(self, req):
        super().__init__(req)
        self.req = req
        self.request_body = req.request.body
        self.base = req.url
        self.error = "The requested allocation could not be fulfilled."

    def __str__(self):
        return self.error


class ContentError(Exception):
    """Exception raised when the API response is not valid JSON.
    
    This exception is used when the server returns a valid response code
    but the content is not in JSON format, indicating the URL might not
    point to a valid NetBox API.
    
    Attributes:
        req: The original requests object
        request_body: The body of the failed request
        base (str): The base URL of the request
        error (str): Fixed error message about invalid content
    """

    def __init__(self, req):
        super().__init__(req)
        self.req = req
        self.request_body = req.request.body
        self.base = req.url
        self.error = (
            "The server returned invalid (non-json) data. Maybe not a NetBox server?"
        )

    def __str__(self):
        return self.error


class Request:
    """Handles HTTP requests to the NetBox API.
    
    This class is responsible for building URLs and making HTTP(S) requests
    to NetBox's API. It handles authentication, pagination, and response
    processing.
    
    Attributes:
        base (str): Base URL for API requests
        filters (dict): Query parameters for filtering results
        key (int): Database ID for specific resource queries
        token (str): Authentication token
        http_session: HTTP session object for making requests
        url (str): Full URL for the current request
        threading (bool): Whether to use threading for pagination
        limit (int): Maximum number of results to return
        offset (int): Number of results to skip
    """

    def __init__(
        self,
        base,
        http_session,
        filters=None,
        limit=None,
        offset=None,
        key=None,
        token=None,
        threading=False,
    ):
        """Initialize a new Request object.
        
        Args:
            base (str): Base URL for API requests
            http_session: HTTP session object for making requests
            filters (dict, optional): Query parameters for filtering results
            limit (int, optional): Maximum number of results to return
            offset (int, optional): Number of results to skip
            key (int, optional): Database ID for specific resource queries
            token (str, optional): Authentication token
            threading (bool, optional): Whether to use threading for pagination
        """
        self.base = self.normalize_url(base)
        self.filters = filters or None
        self.key = key
        self.token = token
        self.http_session = http_session
        self.url = self.base if not key else "{}{}/".format(self.base, key)
        self.threading = threading
        self.limit = limit
        self.offset = offset

    def get_openapi(self):
        """Get the OpenAPI specification from NetBox.
        
        Retrieves the API specification in OpenAPI format. The endpoint
        varies based on the NetBox version.
        
        Returns:
            dict: OpenAPI specification
            
        Raises:
            RequestError: If the request fails
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        current_version = version.parse(self.get_version())
        if current_version >= version.parse("3.5"):
            req = self.http_session.get(
                "{}schema/".format(self.normalize_url(self.base)),
                headers=headers,
            )
        else:
            req = self.http_session.get(
                "{}docs/?format=openapi".format(self.normalize_url(self.base)),
                headers=headers,
            )

        if req.ok:
            return req.json()
        else:
            raise RequestError(req)

    def get_version(self):
        """Get the API version of NetBox.
        
        Makes a GET request to the base URL to read the API version
        from the response headers.
        
        Returns:
            str: Version number, empty string if not present
            
        Raises:
            RequestError: If the request fails
        """
        headers = {
            "Content-Type": "application/json",
        }
        req = self.http_session.get(
            self.normalize_url(self.base),
            headers=headers,
        )
        if req.ok or req.status_code == 403:
            return req.headers.get("API-Version", "")
        else:
            raise RequestError(req)

    def get_status(self):
        """Get the status from NetBox's /api/status/ endpoint.
        
        Returns:
            dict: Status information from NetBox
            
        Raises:
            RequestError: If the request fails
        """
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["authorization"] = "Token {}".format(self.token)
        req = self.http_session.get(
            "{}status/".format(self.normalize_url(self.base)),
            headers=headers,
        )
        if req.ok:
            return req.json()
        else:
            raise RequestError(req)

    def normalize_url(self, url):
        """Ensure URL ends with a trailing slash.
        
        Args:
            url (str): URL to normalize
            
        Returns:
            str: Normalized URL with trailing slash
        """
        if url[-1] != "/":
            return "{}/".format(url)

        return url

    def _make_call(self, verb="get", url_override=None, add_params=None, data=None):
        """Make an HTTP request to the NetBox API.
        
        Internal method that handles the actual HTTP request, including
        headers, authentication, and error handling.
        
        Args:
            verb (str): HTTP method (get, post, put, delete, patch)
            url_override (str, optional): Override the default URL
            add_params (dict, optional): Additional query parameters
            data (dict, optional): Request body data
            
        Returns:
            dict/list: API response data
            
        Raises:
            AllocationError: For 409 Conflict responses
            RequestError: For other failed requests
            ContentError: For non-JSON responses
        """
        if verb in ("post", "put") or verb == "delete" and data:
            headers = {"Content-Type": "application/json"}
        else:
            headers = {"accept": "application/json"}

        if self.token:
            headers["authorization"] = "Token {}".format(self.token)

        params = {}
        if not url_override:
            if self.filters:
                params.update(self.filters)
            if add_params:
                params.update(add_params)

        req = getattr(self.http_session, verb)(
            url_override or self.url, headers=headers, params=params, json=data
        )

        if req.status_code == 409 and verb == "post":
            raise AllocationError(req)
        if verb == "delete":
            if req.ok:
                return True
            else:
                raise RequestError(req)
        elif req.ok:
            try:
                return req.json()
            except json.JSONDecodeError:
                raise ContentError(req)
        else:
            raise RequestError(req)

    def concurrent_get(self, ret, page_size, page_offsets):
        """Make concurrent GET requests for paginated results.
        
        Uses ThreadPoolExecutor to make parallel requests for different
        pages of results.
        
        Args:
            ret (list): List to append results to
            page_size (int): Number of items per page
            page_offsets (list): List of offset values for each page
        """
        futures_to_results = []
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            for offset in page_offsets:
                new_params = {"offset": offset, "limit": page_size}
                futures_to_results.append(
                    pool.submit(self._make_call, add_params=new_params)
                )

            for future in cf.as_completed(futures_to_results):
                result = future.result()
                ret.extend(result["results"])

    def get(self, add_params=None):
        """Make a GET request with automatic pagination handling.
        
        Makes a GET request to NetBox's API and handles pagination
        automatically. Results can be retrieved using iteration.
        
        Args:
            add_params (dict, optional): Additional query parameters
            
        Yields:
            dict: Individual result items
            
        Raises:
            RequestError: If the request fails
            ContentError: If response is not JSON
        """
        if not add_params and self.limit is not None:
            add_params = {"limit": self.limit}
            if self.limit and self.offset is not None:
                add_params["offset"] = self.offset
        req = self._make_call(add_params=add_params)
        if isinstance(req, dict) and req.get("results") is not None:
            self.count = req["count"]
            if self.offset is not None:
                for i in req["results"]:
                    yield i
            elif self.threading:
                ret = req["results"]
                if req.get("next"):
                    page_size = len(req["results"])
                    pages = calc_pages(page_size, req["count"])
                    page_offsets = [
                        increment * page_size for increment in range(1, pages)
                    ]
                    if pages == 1:
                        req = self._make_call(url_override=req.get("next"))
                        ret.extend(req["results"])
                    else:
                        self.concurrent_get(ret, page_size, page_offsets)
                for i in ret:
                    yield i
            else:
                first_run = True
                for i in req["results"]:
                    yield i
                while req["next"]:
                    if first_run:
                        req = self._make_call(
                            add_params={
                                "limit": self.limit or req["count"],
                                "offset": len(req["results"]),
                            }
                        )
                    else:
                        req = self._make_call(url_override=req["next"])
                    first_run = False
                    for i in req["results"]:
                        yield i
        elif isinstance(req, list):
            self.count = len(req)
            for i in req:
                yield i
        else:
            self.count = len(req)
            yield req

    def put(self, data):
        """Make a PUT request to update a resource.
        
        Args:
            data (dict): Data to update the resource with
            
        Returns:
            dict: Updated resource data
            
        Raises:
            RequestError: If the request fails
            ContentError: If response is not JSON
        """
        return self._make_call(verb="put", data=data)

    def post(self, data):
        """Make a POST request to create a new resource.
        
        Args:
            data (dict): Data for the new resource
            
        Returns:
            dict: Created resource data
            
        Raises:
            RequestError: If the request fails
            AllocationError: If allocation fails (409 Conflict)
            ContentError: If response is not JSON
        """
        return self._make_call(verb="post", data=data)

    def delete(self, data=None):
        """Make a DELETE request to remove a resource.
        
        Args:
            data (dict, optional): Additional data for the delete request
            
        Returns:
            bool: True if successful
            
        Raises:
            RequestError: If the request fails
        """
        return self._make_call(verb="delete", data=data)

    def patch(self, data):
        """Make a PATCH request to partially update a resource.
        
        Args:
            data (dict): Partial update data
            
        Returns:
            dict: Updated resource data
            
        Raises:
            RequestError: If the request fails
            ContentError: If response is not JSON
        """
        return self._make_call(verb="patch", data=data)

    def options(self):
        """Make an OPTIONS request to get API information.
        
        Returns:
            dict: API options information
            
        Raises:
            RequestError: If the request fails
            ContentError: If response is not JSON
        """
        return self._make_call(verb="options")

    def get_count(self, *args, **kwargs):
        """Get the total count of objects for the current query.
        
        Makes a query with limit=1 to efficiently get the total count
        without retrieving all objects.
        
        Returns:
            int: Total number of objects
            
        Raises:
            RequestError: If the request fails
            ContentError: If response is not JSON
        """
        if not hasattr(self, "count"):
            self.count = self._make_call(add_params={"limit": 1, "brief": 1})["count"]
        return self.count
