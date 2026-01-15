"""InvenTree plugin to sync stock quantities with Magento 2."""

import logging
import math
from typing import TYPE_CHECKING

from plugin import InvenTreePlugin
from plugin.mixins import EventMixin, SettingsMixin

from .magento_client import MagentoClient, MagentoClientError

if TYPE_CHECKING:
    from part.models import Part

logger = logging.getLogger("inventree")


# Events we care about for stock synchronization
STOCK_EVENTS = frozenset(
    {
        # Generic model events for StockItem
        "stock_stockitem.created",
        "stock_stockitem.saved",
        "stock_stockitem.deleted",
        # Specific stock events
        "stockitem.quantityupdated",
        "stockitem.assignedtocustomer",
        "stockitem.returnedfromcustomer",
        "stockitem.split",
        "stockitem.moved",
        "stockitem.counted",
    }
)


class MagentoStockSyncPlugin(SettingsMixin, EventMixin, InvenTreePlugin):
    """Plugin to synchronize InvenTree stock levels with Magento 2.

    Listens for stock item events and updates Magento 2 when quantities change.
    Uses the legacy single-stock API (/V1/stockItems/:sku).
    """

    PLUGIN_NAME = "MagentoStockSync"
    PLUGIN_SLUG = "magento-stock-sync"
    PLUGIN_TITLE = "Magento 2 Stock Sync"
    PLUGIN_DESCRIPTION = "Synchronize stock quantities from InvenTree to Magento 2"
    PLUGIN_VERSION = "0.1.0"
    PLUGIN_AUTHOR = "Matt Styles"
    
    # Legacy attributes for older InvenTree versions
    NAME = "MagentoStockSync"
    SLUG = "magento-stock-sync"
    TITLE = "Magento 2 Stock Sync"
    DESCRIPTION = "Synchronize stock quantities from InvenTree to Magento 2"
    VERSION = "0.1.0"
    AUTHOR = "Matt Styles"

    SETTINGS = {
        "MAGENTO_URL": {
            "name": "Magento URL",
            "description": "Base URL of your Magento 2 store (e.g., https://shop.example.com)",
            "default": "",
            "required": True,
        },
        "MAGENTO_TOKEN": {
            "name": "Access Token",
            "description": "Magento 2 Integration access token (Bearer token)",
            "default": "",
            "required": True,
            "protected": True,  # Hide value in UI
        },
        "SYNC_ENABLED": {
            "name": "Enable Sync",
            "description": "Enable automatic stock synchronization to Magento 2",
            "validator": bool,
            "default": True,
        },
        "LOG_ONLY": {
            "name": "Log Only Mode",
            "description": "Log sync actions without actually updating Magento (for testing)",
            "validator": bool,
            "default": False,
        },
    }

    _client: MagentoClient | None = None
    _cached_url: str = ""
    _cached_token: str = ""

    @property
    def magento(self) -> MagentoClient | None:
        """Get or create Magento API client.

        Recreates client if settings have changed.
        """
        url = self.get_setting("MAGENTO_URL")
        token = self.get_setting("MAGENTO_TOKEN")

        if not url or not token:
            logger.warning("Magento URL or token not configured")
            return None

        # Recreate client if settings changed
        if self._client is None or self._cached_url != url or self._cached_token != token:
            self._client = MagentoClient(base_url=url, token=token)
            self._cached_url = url
            self._cached_token = token

        return self._client

    def wants_process_event(self, event: str) -> bool:
        """Filter events - only process stock-related events.

        This runs synchronously, so keep it fast.
        """
        return event in STOCK_EVENTS

    def process_event(self, event: str, *args, **kwargs) -> None:
        """Process stock events and sync to Magento 2.

        Args:
            event: Event name (e.g., 'stock_stockitem.saved')
            **kwargs: Event data including 'id' (StockItem primary key)
        """
        # Check if sync is enabled
        if not self.get_setting("SYNC_ENABLED"):
            return

        # Get client (returns None if not configured)
        client = self.magento
        if client is None:
            return

        # Get stock item ID from event
        stock_item_id = kwargs.get("id")
        if not stock_item_id:
            logger.debug(f"Event {event} has no 'id' in kwargs")
            return

        # Handle deleted items specially - we need to get part info before deletion
        # But for .deleted events, the object is already gone, so we need the model name
        if event == "stock_stockitem.deleted":
            # For deleted items, we can't look up the StockItem anymore
            # The part info should be passed in kwargs if available
            part_id = kwargs.get("part_id")
            if not part_id:
                logger.debug(f"Deleted stock item {stock_item_id} - no part_id in kwargs, skipping")
                return
            self._sync_part_by_id(part_id, client, event)
        else:
            self._sync_stock_item(stock_item_id, client, event)

    def _sync_stock_item(self, stock_item_id: int, client: MagentoClient, event: str) -> None:
        """Sync stock for a specific StockItem.

        Args:
            stock_item_id: Primary key of the StockItem
            client: Magento API client
            event: Event name (for logging)
        """
        # Import here to avoid issues when plugin loads outside InvenTree
        try:
            from stock.models import StockItem
        except ImportError:
            logger.error("Could not import StockItem model")
            return

        try:
            stock_item = StockItem.objects.select_related("part").get(pk=stock_item_id)
        except StockItem.DoesNotExist:
            logger.debug(f"StockItem {stock_item_id} not found (may have been deleted)")
            return

        part = stock_item.part
        if not part:
            logger.debug(f"StockItem {stock_item_id} has no associated part")
            return

        self._sync_part(part, client, event)

    def _sync_part_by_id(self, part_id: int, client: MagentoClient, event: str) -> None:
        """Sync stock for a Part by ID.

        Args:
            part_id: Primary key of the Part
            client: Magento API client
            event: Event name (for logging)
        """
        try:
            from part.models import Part
        except ImportError:
            logger.error("Could not import Part model")
            return

        try:
            part = Part.objects.get(pk=part_id)
        except Part.DoesNotExist:
            logger.debug(f"Part {part_id} not found")
            return

        self._sync_part(part, client, event)

    def _sync_part(self, part: "Part", client: MagentoClient, event: str) -> None:
        """Sync stock for a Part to Magento 2.

        Args:
            part: Part instance
            client: Magento API client
            event: Event name (for logging)
        """
        # SKU is the part name
        sku = part.name
        if not sku:
            logger.debug(f"Part {part.pk} has no name, skipping sync")
            return

        # Get total stock across all locations
        total_qty = float(part.total_stock)

        log_only = self.get_setting("LOG_ONLY")

        try:
            # Get current Magento quantity
            m2_qty = client.get_stock_qty(sku)

            if m2_qty is None:
                logger.warning(f"[{event}] SKU '{sku}' not found in Magento, skipping sync")
                return

            # Compare quantities (use tolerance for float comparison)
            if math.isclose(total_qty, m2_qty, rel_tol=1e-9, abs_tol=0.001):
                logger.debug(f"[{event}] SKU '{sku}' already in sync (qty={total_qty})")
                return

            # Update Magento
            if log_only:
                logger.info(
                    f"[LOG_ONLY] [{event}] Would sync SKU '{sku}': "
                    f"Magento {m2_qty} -> InvenTree {total_qty}"
                )
            else:
                success = client.update_stock_qty(sku, total_qty)
                if success:
                    logger.info(
                        f"[{event}] Synced SKU '{sku}': Magento {m2_qty} -> {total_qty}"
                    )
                else:
                    logger.error(f"[{event}] Failed to sync SKU '{sku}'")

        except MagentoClientError as e:
            logger.error(f"[{event}] Magento API error for SKU '{sku}': {e}")
