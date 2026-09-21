-- CentralMatch (NEW — talks to central 2v2 matchmaker on Render).
-- Does not touch the old MatchMaking system. Old UI keeps working.
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local BASE_URL = "https://roblox-matchmaker.onrender.com"
local POLL_INTERVAL = 3
local POLL_TIMEOUT = 120

local event = ReplicatedStorage:WaitForChild("CentralMatchEvent")

local function api(method, path, body)
	local url = BASE_URL .. path
	local ok, res = pcall(function()
		if method == "GET" then
			return HttpService:GetAsync(url)
		end
		return HttpService:PostAsync(
			url,
			HttpService:JSONEncode(body or {}),
			Enum.HttpContentType.ApplicationJson
		)
	end)
	if not ok then
		return nil
	end
	local parsed
	ok, parsed = pcall(HttpService.JSONDecode, HttpService, res)
	if not ok then
		return nil
	end
	return parsed
end

local pollers = {}

local function stopPoller(userId)
	local h = pollers[userId]
	if h then
		task.cancel(h)
		pollers[userId] = nil
	end
end

local function startPoller(player)
	local userId = tostring(player.UserId)
	stopPoller(userId)
	pollers[userId] = task.spawn(function()
		local waited = 0
		while waited < POLL_TIMEOUT do
			task.wait(POLL_INTERVAL)
			waited += POLL_INTERVAL
			if not player.Parent then
				break
			end
			local st = api("GET", "/v1/queue/status?user_id=" .. userId)
			if st and st.state == "assigned" and st.match_id ~= "" then
				local m = api("GET", "/v1/match/" .. st.match_id)
				if m then
					event:FireClient(player, "Assigned", m)
				end
				break
			elseif st and st.state == "idle" then
				break
			end
		end
		pollers[userId] = nil
	end)
end

event.OnServerEvent:Connect(function(player, action, partyId)
	if action == "Join" then
		local res = api("POST", "/v1/queue/join", {
			user_id = tostring(player.UserId),
			party_id = partyId or "",
			mode = "2v2",
		})
		if res then
			if res.state == "assigned" and res.match_id ~= "" then
				local m = api("GET", "/v1/match/" .. res.match_id)
				if m then
					event:FireClient(player, "Assigned", m)
				end
			else
				event:FireClient(player, "Queued", { position = res.position or 0 })
				startPoller(player)
			end
		else
			event:FireClient(player, "Error", { message = "matchmaker unreachable" })
		end
	elseif action == "Leave" then
		stopPoller(tostring(player.UserId))
		api("POST", "/v1/queue/leave", { user_id = tostring(player.UserId) })
		event:FireClient(player, "Left", {})
	end
end)

Players.PlayerRemoving:Connect(function(player)
	local userId = tostring(player.UserId)
	stopPoller(userId)
	api("POST", "/v1/queue/leave", { user_id = userId })
end)
