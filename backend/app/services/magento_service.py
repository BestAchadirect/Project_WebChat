from typing import List, Optional, Dict, Any
import httpx
from app.core.logging import get_logger
from app.core.exceptions import MagentoAPIException
from app.schemas.product import Product

logger = get_logger(__name__)

class MagentoService:
    """Service for interacting with Magento 2 REST API."""
    
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def search_products(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Product]:
        """
        Search for products in Magento catalog.
        
        Args:
            query: Search query string
            limit: Maximum number of products to return
            filters: Additional filters (category, price range, etc.)
        
        Returns:
            List of Product objects
        """
        try:
            # Build search criteria
            search_criteria = {
                "searchCriteria": {
                    "filterGroups": [
                        {
                            "filters": [
                                {
                                    "field": "name",
                                    "value": f"%{query}%",
                                    "conditionType": "like"
                                }
                            ]
                        }
                    ],
                    "pageSize": limit,
                    "currentPage": 1
                }
            }
            
            # Add additional filters if provided
            if filters:
                # TODO: Implement additional filter logic
                pass
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/rest/V1/products",
                    headers=self.headers,
                    params=search_criteria
                )
                
                if response.status_code != 200:
                    logger.error(f"Magento API error: {response.status_code} - {response.text}")
                    raise MagentoAPIException(f"Failed to search products: {response.status_code}")
                
                data = response.json()
                products = []
                
                for item in data.get("items", []):
                    # Extract product information
                    product = self._parse_product(item)
                    if product:
                        products.append(product)
                
                return products[:limit]
                
        except httpx.HTTPError as e:
            logger.error(f"HTTP error during product search: {e}")
            raise MagentoAPIException(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during product search: {e}")
            raise MagentoAPIException(f"Unexpected error: {str(e)}")
    
    async def get_product_by_sku(self, sku: str) -> Optional[Product]:
        """Get a single product by SKU."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/rest/V1/products/{sku}",
                    headers=self.headers
                )
                
                if response.status_code == 404:
                    return None
                
                if response.status_code != 200:
                    raise MagentoAPIException(f"Failed to get product: {response.status_code}")
                
                data = response.json()
                return self._parse_product(data)
                
        except Exception as e:
            logger.error(f"Error getting product by SKU: {e}")
            raise
    
    def _parse_product(self, item: dict) -> Optional[Product]:
        """Parse Magento product data into Product schema."""
        try:
            # Extract custom attributes
            custom_attrs = {attr["attribute_code"]: attr["value"] 
                          for attr in item.get("custom_attributes", [])}
            
            # Get image URL
            image_url = None
            if "media_gallery_entries" in item and item["media_gallery_entries"]:
                image_url = f"{self.base_url}/media/catalog/product{item['media_gallery_entries'][0].get('file', '')}"
            
            # Get product URL
            product_url = custom_attrs.get("url_key")
            if product_url:
                product_url = f"{self.base_url}/{product_url}.html"
            
            return Product(
                id=str(item.get("id", "")),
                sku=item.get("sku", ""),
                name=item.get("name", ""),
                price=float(item.get("price", 0)),
                image_url=image_url,
                url=product_url,
                description=custom_attrs.get("description", ""),
                in_stock=item.get("status", 1) == 1
            )
        except Exception as e:
            logger.error(f"Error parsing product: {e}")
            return None
