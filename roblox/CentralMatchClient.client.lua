-- CentralMatchClient (NEW): minimal 2v2 test button. Old UI untouched.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local event = ReplicatedStorage:WaitForChild("CentralMatchEvent")

local gui = Instance.new("ScreenGui")
gui.Name = "CentralMatchTest"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local btn = Instance.new("TextButton")
btn.Size = UDim2.new(0, 200, 0, 50)
btn.Position = UDim2.new(0, 10, 0, 200)
btn.Text = "Join 2v2 (Central)"
btn.Parent = gui

local label = Instance.new("TextLabel")
label.Size = UDim2.new(0, 300, 0, 30)
label.Position = UDim2.new(0, 10, 0, 255)
label.Text = "idle"
label.Parent = gui

btn.MouseButton1Click:Connect(function()
	label.Text = "joining..."
	event:FireServer("Join")
end)

event.OnClientEvent:Connect(function(kind, data)
	if kind == "Queued" then
		label.Text = "queued #" .. tostring(data.position)
		btn.Text = "Leave"
	elseif kind == "Assigned" then
		local a = table.concat(data.team_a, ",")
		local b = table.concat(data.team_b, ",")
		label.Text = "MATCH! A:" .. a .. " B:" .. b
		btn.Text = "Join 2v2 (Central)"
	elseif kind == "Left" then
		label.Text = "idle"
		btn.Text = "Join 2v2 (Central)"
	elseif kind == "Error" then
		label.Text = "error: " .. tostring(data.message)
	end
end)
