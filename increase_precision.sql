-- Increase precision for price/amount fields from Numeric(10,2) to Numeric(15,2)
-- This allows values up to 9,999,999,999,999.99 (almost 10 trillion)

-- Start transaction to ensure atomicity
BEGIN;

-- Update orders.total_amount precision
ALTER TABLE orders 
ALTER COLUMN total_amount TYPE NUMERIC(15,2);

-- Update order_items.price precision  
ALTER TABLE order_items 
ALTER COLUMN price TYPE NUMERIC(15,2);

-- Update products.price precision
ALTER TABLE products 
ALTER COLUMN price TYPE NUMERIC(15,2);

-- Commit the changes
COMMIT;

-- Verify the changes
SELECT 
    table_name,
    column_name,
    data_type,
    numeric_precision,
    numeric_scale
FROM information_schema.columns 
WHERE table_name IN ('orders', 'order_items', 'products') 
  AND column_name IN ('total_amount', 'price')
ORDER BY table_name, column_name;
