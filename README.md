# InvenTree Magento 2 Stock Sync Plugin

An InvenTree plugin that automatically synchronizes stock quantities to Magento 2 when stock levels change.

## Features

- **Real-time sync**: Triggers on stock item create/update/delete events
- **Automatic quantity calculation**: Syncs total stock across all locations for a part
- **SKU mapping**: Uses `part.name` as the Magento SKU
- **Graceful handling**: Skips SKUs not found in Magento (logs warning)
- **Debug mode**: "Log Only" mode for testing without updating Magento

## Requirements

- InvenTree 0.14.0+
- Magento 2.x with REST API enabled
- Magento Integration access token

## Installation

### Via pip (recommended)

```bash
pip install inventree-magento-sync
```

### Development install

```bash
cd /path/to/inventre-stock-syncer
pip install -e ".[dev]"
```

## Configuration

### 1. Enable Event Integration

In InvenTree Admin, go to **Settings > Plugin Settings** and enable:
- **Enable Event Integration**

### 2. Activate the Plugin

Go to **Admin > Plugins** and activate **Magento 2 Stock Sync**.

### 3. Configure Plugin Settings

| Setting | Description |
|---------|-------------|
| **Magento URL** | Base URL of your Magento store (e.g., `https://shop.example.com`) |
| **Access Token** | Magento Integration access token |
| **Enable Sync** | Toggle sync on/off |
| **Log Only Mode** | Test mode - logs actions without updating Magento |

### Getting a Magento Access Token

1. Go to Magento Admin > **System > Extensions > Integrations**
2. Click **Add New Integration**
3. Set a name (e.g., "InvenTree Sync")
4. Under **API**, grant access to:
   - `Catalog > Inventory > Products`
   - `Catalog > Inventory > Stock Items`
5. Save and activate the integration
6. Copy the **Access Token**

## How It Works

### Event Flow

```
InvenTree StockItem event
        │
        ▼
Plugin receives event (stock_stockitem.saved, etc.)
        │
        ▼
Get Part from StockItem
        │
        ▼
Calculate total stock (part.total_stock)
        │
        ▼
GET /V1/stockItems/:sku (compare M2 qty)
        │
        ▼ (if different)
PUT /V1/products/:sku/stockItems/:itemId
```

### Supported Events

| Event | Trigger |
|-------|---------|
| `stock_stockitem.created` | New stock item added |
| `stock_stockitem.saved` | Stock item updated |
| `stock_stockitem.deleted` | Stock item removed |
| `stockitem.quantityupdated` | Quantity directly modified |
| `stockitem.counted` | Stock count performed |
| `stockitem.moved` | Stock moved between locations |

### SKU Mapping

The plugin uses `part.name` as the Magento SKU. Ensure your InvenTree part names match your Magento SKUs exactly.

## Troubleshooting

### Check logs

InvenTree logs sync events at INFO level:

```
[stock_stockitem.saved] Synced SKU 'WIDGET-001': Magento 10 -> 25
```

Warnings for missing SKUs:

```
[stock_stockitem.saved] SKU 'UNKNOWN-SKU' not found in Magento, skipping sync
```

### Test connection

Enable "Log Only Mode" to verify events are being captured without modifying Magento.

### Common issues

| Issue | Solution |
|-------|----------|
| "Magento URL or token not configured" | Check plugin settings |
| SKU not found | Verify part.name matches Magento SKU exactly |
| 401 Unauthorized | Check access token and permissions |
| Timeout errors | Check network/firewall, increase timeout |

## Development

### Run tests

```bash
pip install -e ".[dev]"
pytest -v
```

### Code style

```bash
ruff check .
ruff format .
```

## License

MIT License
