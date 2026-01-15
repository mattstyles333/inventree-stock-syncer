"""Tests for Magento 2 API client."""

import pytest
import responses

from inventree_magento_sync.magento_client import MagentoClient, MagentoClientError


@pytest.fixture
def client():
    """Create a test Magento client."""
    return MagentoClient(base_url="https://shop.example.com", token="test_token_123")


class TestMagentoClient:
    """Tests for MagentoClient."""

    def test_init(self, client):
        """Test client initialization."""
        assert client.base_url == "https://shop.example.com"
        assert client.token == "test_token_123"
        assert "Bearer test_token_123" in client.session.headers["Authorization"]

    def test_url_building(self, client):
        """Test API URL construction."""
        assert client._url("/stockItems/ABC") == "https://shop.example.com/rest/V1/stockItems/ABC"

    def test_sku_encoding(self, client):
        """Test SKU URL encoding for special characters."""
        assert client._encode_sku("simple-sku") == "simple-sku"
        assert client._encode_sku("sku/with/slashes") == "sku%2Fwith%2Fslashes"
        assert client._encode_sku("sku with spaces") == "sku%20with%20spaces"

    @responses.activate
    def test_get_stock_item_success(self, client):
        """Test successful stock item retrieval."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/TEST-SKU",
            json={"item_id": 123, "qty": 50, "is_in_stock": True},
            status=200,
        )

        result = client.get_stock_item("TEST-SKU")

        assert result is not None
        assert result["item_id"] == 123
        assert result["qty"] == 50
        assert result["is_in_stock"] is True

    @responses.activate
    def test_get_stock_item_not_found(self, client):
        """Test stock item not found returns None."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/UNKNOWN-SKU",
            json={"message": "Product not found"},
            status=404,
        )

        result = client.get_stock_item("UNKNOWN-SKU")

        assert result is None

    @responses.activate
    def test_get_stock_qty(self, client):
        """Test getting stock quantity."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/TEST-SKU",
            json={"item_id": 123, "qty": 75.5, "is_in_stock": True},
            status=200,
        )

        qty = client.get_stock_qty("TEST-SKU")

        assert qty == 75.5

    @responses.activate
    def test_get_stock_qty_not_found(self, client):
        """Test getting stock qty for missing SKU returns None."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/UNKNOWN",
            status=404,
        )

        qty = client.get_stock_qty("UNKNOWN")

        assert qty is None

    @responses.activate
    def test_update_stock_qty_success(self, client):
        """Test successful stock update."""
        # First call to get stock item
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/TEST-SKU",
            json={"item_id": 456, "qty": 10, "is_in_stock": True},
            status=200,
        )
        # Second call to update
        responses.add(
            responses.PUT,
            "https://shop.example.com/rest/V1/products/TEST-SKU/stockItems/456",
            json=456,  # Magento returns item_id on success
            status=200,
        )

        result = client.update_stock_qty("TEST-SKU", 100)

        assert result is True
        # Verify the PUT request body
        put_request = responses.calls[1]
        assert put_request.request.body == b'{"stockItem": {"qty": 100, "is_in_stock": true}}'

    @responses.activate
    def test_update_stock_qty_sku_not_found(self, client):
        """Test update fails gracefully when SKU not found."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/UNKNOWN",
            status=404,
        )

        result = client.update_stock_qty("UNKNOWN", 50)

        assert result is False

    @responses.activate
    def test_update_stock_qty_sets_out_of_stock(self, client):
        """Test that qty=0 sets is_in_stock=False."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/TEST-SKU",
            json={"item_id": 789, "qty": 10, "is_in_stock": True},
            status=200,
        )
        responses.add(
            responses.PUT,
            "https://shop.example.com/rest/V1/products/TEST-SKU/stockItems/789",
            json=789,
            status=200,
        )

        result = client.update_stock_qty("TEST-SKU", 0)

        assert result is True
        put_request = responses.calls[1]
        assert put_request.request.body == b'{"stockItem": {"qty": 0, "is_in_stock": false}}'

    @responses.activate
    def test_test_connection_success(self, client):
        """Test connection test success."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/store/storeConfigs",
            json=[{"id": 1, "code": "default"}],
            status=200,
        )

        assert client.test_connection() is True

    @responses.activate
    def test_test_connection_failure(self, client):
        """Test connection test failure."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/store/storeConfigs",
            json={"message": "Unauthorized"},
            status=401,
        )

        assert client.test_connection() is False

    @responses.activate
    def test_api_error_raises_exception(self, client):
        """Test that API errors raise MagentoClientError."""
        responses.add(
            responses.GET,
            "https://shop.example.com/rest/V1/stockItems/TEST-SKU",
            json={"message": "Internal error"},
            status=500,
        )

        with pytest.raises(MagentoClientError):
            client.get_stock_item("TEST-SKU")
