-- Add status column to order_items table for seller-specific status tracking
-- This allows each seller to manage their items independently

BEGIN;

-- Add status column to order_items table
ALTER TABLE order_items 
ADD COLUMN status VARCHAR(20) DEFAULT 'pending';

-- Add check constraint for valid statuses
ALTER TABLE order_items 
ADD CONSTRAINT order_items_status_check 
CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled'));

-- Update existing items to have 'pending' status
UPDATE order_items SET status = 'pending' WHERE status IS NULL;

-- Make the column NOT NULL after setting default values
ALTER TABLE order_items 
ALTER COLUMN status SET NOT NULL;

COMMIT;

-- Verify the changes
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns 
WHERE table_name = 'order_items' AND column_name = 'status';
