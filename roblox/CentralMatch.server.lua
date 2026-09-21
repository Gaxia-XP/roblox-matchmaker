-- Central 2v2 matchmaking bridge. Server-side only.
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local BASE_URL = "https://roblox-matchmaker.onrender.com"
local POLL_INTERVAL = 3
local POLL_TIMEOUT = 120

local event = ReplicatedStorage:WaitForChild("CentralMatchEvent")
local pollers = {}
local busy = {}

local function api(method, path, body)
	local request = {
		Url = BASE_URL .. path,
		Method = method,
		Headers = { ["Content-Type"] = "application/json" },
	}
	if body then
		request.Body = HttpService:JSONEncode(body)
	end

	local ok, response = pcall(HttpService.RequestAsync, HttpService, request)
	if not ok or not response.Success then
		return nil
	end

	local decoded
	ok, decoded = pcall(HttpService.JSONDecode, HttpService, response.Body)
	if not ok then
		return nil
	end
	return decoded
end

local function stopPoller(userId)
	local thread = pollers[userId]
	if thread then
		task.cancel(thread)
		pollers[userId] = nil
	end
end

local function leaveQueue(userId)
	stopPoller(userId)
	return api("POST", "/v1/queue/leave", { user_id = userId })
end

local function deliverAssignment(player, matchId)
	local match = api("GET", "/v1/match/" .. matchId)
	if match and player.Parent == Players then
		event:FireClient(player, "Assigned", match)
		return true
	end
	return false
end

local function startPoller(player)
	local userId = tostring(player.UserId)
	stopPoller(userId)
	pollers[userId] = task.spawn(function()
		local waited = 0
		while waited < POLL_TIMEOUT and player.Parent == Players do
			task.wait(POLL_INTERVAL)
			waited += POLL_INTERVAL
			local status = api("GET", "/v1/queue/status?user_id=" .. userId)
			if status and status.state == "assigned" and status.match_id ~= "" then
				deliverAssignment(player, status.match_id)
				pollers[userId] = nil
				return
			elseif status and status.state == "idle" then
				pollers[userId] = nil
				return
			end
		end

		pollers[userId] = nil
		if player.Parent == Players then
			api("POST", "/v1/queue/leave", { user_id = userId })
			event:FireClient(player, "Error", { message = "search timed out" })
		end
	end)
end

event.OnServerEvent:Connect(function(player, action)
	local userId = tostring(player.UserId)
	if action == "ClientReady" then
		player:SetAttribute("CentralMatchClientReady", true)
		return
	end
	if busy[userId] then
		return
	end
	if action ~= "Join" and action ~= "Leave" then
		return
	end

	busy[userId] = true
	if action == "Join" then
		-- MVP is solo queue. Never trust a client-supplied party id.
		local response = api("POST", "/v1/queue/join", {
			user_id = userId,
			party_id = "",
			mode = "2v2",
		})
		if response then
			if response.state == "assigned" and response.match_id ~= "" then
				deliverAssignment(player, response.match_id)
			else
				event:FireClient(player, "Queued", { position = response.position or 0 })
				startPoller(player)
			end
		else
			event:FireClient(player, "Error", { message = "matchmaker unreachable" })
		end
	else
		leaveQueue(userId)
		if player.Parent == Players then
			event:FireClient(player, "Left", {})
		end
	end
	busy[userId] = nil
end)

Players.PlayerRemoving:Connect(function(player)
	local userId = tostring(player.UserId)
	busy[userId] = nil
	leaveQueue(userId)
end)
