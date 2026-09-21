-- Connect the existing Cooking Battle Duos button to the central matchmaker.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local event = ReplicatedStorage:WaitForChild("CentralMatchEvent")
local matchmakingGui = player:WaitForChild("PlayerGui"):WaitForChild("Matchmaking")
local party = matchmakingGui:WaitForChild("Party")
local header = party:WaitForChild("Header")
local button = party:WaitForChild("Action"):WaitForChild("Duos")

local state = "idle"

local function setButton(text, enabled)
	button.Text = text
	button.Active = enabled
	button.AutoButtonColor = enabled
end

local function reset()
	state = "idle"
	header.Text = "Your Party (1/2)"
	setButton("Duos", true)
	matchmakingGui:SetAttribute("CentralMatchState", "idle")
	matchmakingGui:SetAttribute("CentralMatchId", nil)
end

button.Activated:Connect(function()
	if state == "idle" or state == "error" then
		state = "joining"
		header.Text = "Joining central queue..."
		setButton("Joining...", false)
		event:FireServer("Join")
	elseif state == "queued" then
		state = "leaving"
		header.Text = "Leaving queue..."
		setButton("Leaving...", false)
		event:FireServer("Leave")
	end
end)

event.OnClientEvent:Connect(function(kind, data)
	if kind == "Queued" then
		state = "queued"
		header.Text = "Searching for a 2v2 match (" .. tostring(data.position or 0) .. " waiting)"
		setButton("Leave Queue", true)
		matchmakingGui:SetAttribute("CentralMatchState", "queued")
	elseif kind == "Assigned" then
		state = "assigned"
		local userId = tostring(player.UserId)
		local team = table.find(data.team_a or {}, userId) and "A" or "B"
		header.Text = "MATCH! Team " .. team .. " - " .. tostring(data.id)
		setButton("Matched", false)
		matchmakingGui:SetAttribute("CentralMatchState", "assigned")
		matchmakingGui:SetAttribute("CentralMatchId", tostring(data.id or ""))
		matchmakingGui:SetAttribute("CentralTeamA", table.concat(data.team_a or {}, ","))
		matchmakingGui:SetAttribute("CentralTeamB", table.concat(data.team_b or {}, ","))
	elseif kind == "Left" then
		reset()
	elseif kind == "Error" then
		state = "error"
		header.Text = "Matchmaking error: " .. tostring(data.message or "unknown")
		setButton("Retry Duos", true)
		matchmakingGui:SetAttribute("CentralMatchState", "error")
	end
end)

reset()
event:FireServer("ClientReady")
