#!lua
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local member = ARGV[3]

local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

if limit <= 0 then
  return {0, 0, now + window, window}
end

redis.call('ZREMRANGEBYSCORE', key, '-inf', string.format('(%d', now - window))
local count = redis.call('ZCARD', key)
local allowed = 0
if count < limit then
  redis.call('ZADD', key, now, member)
  count = count + 1
  allowed = 1
end

local oldest = tonumber(redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2])
local newest = tonumber(redis.call('ZRANGE', key, -1, -1, 'WITHSCORES')[2])
redis.call('PEXPIRE', key, newest + window - now + 1)

local free_at = oldest + window + 1
return {allowed, math.max(0, limit - count), free_at, free_at - now}
