"""Magento 2 REST API client for stock management."""

import logging
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("inventree")


class MagentoClientError(Exception):
    """Base exception for Magento API errors."""


class MagentoClient:
    """HTTP client for Magento 2 REST API (legacy single-stock)."""

    TIMEOUT = 30  # seconds
    RETRY_TOTAL = 3
    RETRY_BACKOFF = 1  # seconds
    RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(self, base_url: str, token: str):
        """Initialize client with Magento 2 credentials.

        Args:
            base_url: Magento base URL (e.g., https://shop.example.com)
            token: Integration access token (Bearer token)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        # Configure retry strategy for transient failures
        retry_strategy = Retry(
            total=self.RETRY_TOTAL,
            backoff_factor=self.RETRY_BACKOFF,
            status_forcelist=self.RETRY_STATUS_CODES,
            allowed_methods=["GET", "PUT", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _url(self, path: str) -> str:
        """Build full API URL."""
        return f"{self.base_url}/rest/V1{path}"

    def _encode_sku(self, sku: str) -> str:
        """URL-encode SKU for API path (handles special chars like /)."""
        return quote(sku, safe="")

    def get_stock_item(self, sku: str) -> dict | None:
        """Get stock item data for a SKU.

        Args:
            sku: Product SKU (maps to InvenTree part.name)

        Returns:
            Stock item dict with qty, item_id, is_in_stock, etc.
            None if SKU not found in Magento.

        Raises:
            MagentoClientError: On API errors (except 404)
        """
        encoded_sku = self._encode_sku(sku)
        url = self._url(f"/stockItems/{encoded_sku}")

        try:
            response = self.session.get(url, timeout=self.TIMEOUT)

            if response.status_code == 404:
                logger.debug(f"SKU '{sku}' not found in Magento")
                return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Timeout getting stock for SKU '{sku}'")
            raise MagentoClientError(f"Timeout getting stock for SKU '{sku}'")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting stock for SKU '{sku}': {e}")
            raise MagentoClientError(f"API error for SKU '{sku}': {e}")

    def get_stock_qty(self, sku: str) -> float | None:
        """Get current stock quantity for a SKU.

        Args:
            sku: Product SKU

        Returns:
            Current quantity in Magento, or None if SKU not found.
        """
        stock_item = self.get_stock_item(sku)
        if stock_item is None:
            return None
        return float(stock_item.get("qty", 0))

    def update_stock_qty(self, sku: str, qty: float, is_in_stock: bool | None = None) -> bool:
        """Update stock quantity for a SKU.

        Args:
            sku: Product SKU
            qty: New quantity to set
            is_in_stock: Override in_stock status (default: auto based on qty > 0)

        Returns:
            True if update succeeded, False otherwise.

        Raises:
            MagentoClientError: On API errors
        """
        # First get the stock item to get item_id
        stock_item = self.get_stock_item(sku)
        if stock_item is None:
            logger.warning(f"Cannot update stock: SKU '{sku}' not found in Magento")
            return False

        item_id = stock_item.get("item_id")
        if not item_id:
            logger.error(f"No item_id found for SKU '{sku}'")
            return False

        # Determine is_in_stock
        if is_in_stock is None:
            is_in_stock = qty > 0

        encoded_sku = self._encode_sku(sku)
        url = self._url(f"/products/{encoded_sku}/stockItems/{item_id}")

        payload = {"stockItem": {"qty": qty, "is_in_stock": is_in_stock}}

        try:
            response = self.session.put(url, json=payload, timeout=self.TIMEOUT)
            response.raise_for_status()
            logger.info(f"Updated Magento stock for '{sku}': qty={qty}, in_stock={is_in_stock}")
            return True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout updating stock for SKU '{sku}'")
            raise MagentoClientError(f"Timeout updating stock for SKU '{sku}'")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating stock for SKU '{sku}': {e}")
            raise MagentoClientError(f"API error updating SKU '{sku}': {e}")

    def test_connection(self) -> bool:
        """Test API connection by fetching store config.

        Returns:
            True if connection successful, False otherwise.
        """
        url = self._url("/store/storeConfigs")
        try:
            response = self.session.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()
            logger.info("Magento API connection test successful")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Magento API connection test failed: {e}")
            return False
