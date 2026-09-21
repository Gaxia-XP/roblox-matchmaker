-- MatchmakerClient: thin client for the central 2v2 matchmaker.
-- Put BASE_URL in a ModuleScript/StringValue configured per game.
-- Server-side only (HttpService). Never trust client-sent queue state.

local HttpService = game:GetService("HttpService")

local MatchmakerClient = {}
MatchmakerClient.BASE_URL = "https://roblox-matchmaker.onrender.com"

local function call(method, path, body)
	local url = MatchmakerClient.BASE_URL .. path
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
		return nil, tostring(res)
	end
	local parsed
	ok, parsed = pcall(HttpService.JSONDecode, HttpService, res)
	if not ok then
		return nil, "bad-json"
	end
	return parsed, nil
end

function MatchmakerClient.Join(userId, partyId)
	return call("POST", "/v1/queue/join", {
		user_id = tostring(userId),
		party_id = partyId or "",
		mode = "2v2",
	})
end

function MatchmakerClient.Leave(userId)
	return call("POST", "/v1/queue/leave", { user_id = tostring(userId) })
end

function MatchmakerClient.Status(userId)
	return call("GET", "/v1/queue/status?user_id=" .. tostring(userId))
end

function MatchmakerClient.Match(matchId)
	return call("GET", "/v1/match/" .. matchId)
end

return MatchmakerClient
