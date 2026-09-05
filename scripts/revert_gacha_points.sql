-- 回退卡牌系统测试期间的积分变动
BEGIN;

-- 回退积分（撤销卡牌系统造成的 net_change）
UPDATE shared.user_points SET points = points - 1000 WHERE user_id = 5071823971 AND chat_id = -1002434265967;
UPDATE shared.user_points SET points = points - 910 WHERE user_id = 6217827218 AND chat_id = -1003872095297;
UPDATE shared.user_points SET points = points + 150 WHERE user_id = 6217827218 AND chat_id = -1002434265967;
UPDATE shared.user_points SET points = points + 105 WHERE user_id = 6901796814 AND chat_id = -1002434265967;

-- 删除所有卡牌系统相关的交易记录
DELETE FROM shared.points_transaction
WHERE reason LIKE '%卡牌%' OR reason LIKE '%赛季%' OR reason LIKE '%十连%' OR reason LIKE '%交易手续费%' OR reason LIKE '%全套兑换%';

COMMIT;
