extends Control

var name_input: LineEdit
var room_input: LineEdit
var host_port_input: LineEdit
var host_password_input: LineEdit
var ip_input: LineEdit
var join_port_input: LineEdit
var join_password_input: LineEdit
var status_label: Label
var rooms_list: ItemList
var room_hint_label: Label

var _room_rows: Array = []
var _selected_room: Dictionary = {}

func _ready() -> void:
	_build_ui()
	name_input.text = LobbyState.local_player_name
	NetworkManager.connection_status_changed.connect(_on_connection_status_changed)
	NetworkManager.room_list_changed.connect(_refresh_room_list)
	NetworkManager.start_room_discovery()
	_refresh_room_list()

func _exit_tree() -> void:
	if not LobbyState.connected:
		NetworkManager.start_room_discovery()

func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.color = Color(0.04, 0.04, 0.05)
	add_child(bg)

	var root := MarginContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("margin_left", 28)
	root.add_theme_constant_override("margin_top", 24)
	root.add_theme_constant_override("margin_right", 28)
	root.add_theme_constant_override("margin_bottom", 24)
	add_child(root)

	var shell := VBoxContainer.new()
	shell.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	shell.size_flags_vertical = Control.SIZE_EXPAND_FILL
	shell.add_theme_constant_override("separation", 16)
	root.add_child(shell)

	var topbar := HBoxContainer.new()
	topbar.add_theme_constant_override("separation", 12)
	shell.add_child(topbar)

	var back := Button.new()
	back.text = "← Main Menu"
	back.custom_minimum_size = Vector2(150, 40)
	back.pressed.connect(_on_back_pressed)
	topbar.add_child(back)

	var title_box := VBoxContainer.new()
	title_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	topbar.add_child(title_box)

	var title := Label.new()
	title.text = "Multiplayer"
	title.add_theme_font_size_override("font_size", 34)
	title_box.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "Discover LAN rooms, host a lobby, or join manually."
	subtitle.modulate = Color(0.74, 0.76, 0.81)
	title_box.add_child(subtitle)

	status_label = Label.new()
	status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	status_label.custom_minimum_size = Vector2(260, 0)
	status_label.text = "Scanning LAN for rooms..."
	topbar.add_child(status_label)

	var body := HSplitContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.split_offset = 460
	shell.add_child(body)

	var left := VBoxContainer.new()
	left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left.add_theme_constant_override("separation", 14)
	body.add_child(left)

	left.add_child(_build_identity_card())
	left.add_child(_build_rooms_card())

	var right := VBoxContainer.new()
	right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(right)

	var tabs := TabContainer.new()
	tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	right.add_child(tabs)

	var host_panel := _build_host_card()
	host_panel.name = "Create Room"
	tabs.add_child(host_panel)

	var join_panel := _build_join_card()
	join_panel.name = "Join Room"
	tabs.add_child(join_panel)

func _build_identity_card() -> Control:
	var panel := _make_card("Player Profile", "Used for both hosting and joining during local testing.")
	var content := _card_content(panel)
	name_input = _make_input("Player name", "Aerin")
	content.add_child(_field_with_label("Player name", name_input))
	return panel

func _build_rooms_card() -> Control:
	var panel := _make_card("Available Rooms", "Rooms visible here are discovered on your local network.")
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var content := _card_content(panel)

	rooms_list = ItemList.new()
	rooms_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rooms_list.size_flags_vertical = Control.SIZE_EXPAND_FILL
	rooms_list.select_mode = ItemList.SELECT_SINGLE
	rooms_list.item_selected.connect(_on_room_item_selected)
	content.add_child(rooms_list)

	room_hint_label = Label.new()
	room_hint_label.text = "No LAN rooms found yet. You can still join manually."
	room_hint_label.modulate = Color(0.68, 0.71, 0.77)
	room_hint_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	content.add_child(room_hint_label)

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 12)
	content.add_child(actions)

	var refresh_button := _make_secondary_button("Refresh")
	refresh_button.pressed.connect(_on_refresh_rooms_pressed)
	actions.add_child(refresh_button)

	var join_selected_button := _make_primary_button("Join Selected Room")
	join_selected_button.pressed.connect(_on_join_selected_pressed)
	actions.add_child(join_selected_button)

	return panel

func _build_host_card() -> Control:
	var panel := _make_card("Create Room", "Host a multiplayer lobby on your machine.")
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var content := _card_content(panel)

	room_input = _make_input("Room name", "Across the Planes")
	content.add_child(_field_with_label("Room name", room_input))

	host_port_input = _make_input("Port", "7777")
	host_port_input.text = "7777"
	content.add_child(_field_with_label("Port", host_port_input))

	host_password_input = _make_input("Password", "Leave blank for open room")
	host_password_input.secret = true
	content.add_child(_field_with_label("Password (optional)", host_password_input))

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 12)
	content.add_child(actions)

	var host_button := _make_primary_button("Host Lobby")
	host_button.pressed.connect(_on_host_pressed)
	actions.add_child(host_button)

	var open_sandbox := _make_secondary_button("Open Sandbox Only")
	open_sandbox.pressed.connect(_on_open_sandbox_pressed)
	actions.add_child(open_sandbox)

	return panel

func _build_join_card() -> Control:
	var panel := _make_card("Join Room", "Select from LAN rooms on the left or type the host IP manually.")
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var content := _card_content(panel)

	ip_input = _make_input("Host IP", "127.0.0.1")
	ip_input.text = "127.0.0.1"
	content.add_child(_field_with_label("Host IP", ip_input))

	join_port_input = _make_input("Port", "7777")
	join_port_input.text = "7777"
	content.add_child(_field_with_label("Port", join_port_input))

	join_password_input = _make_input("Password", "Enter room password if required")
	join_password_input.secret = true
	content.add_child(_field_with_label("Password", join_password_input))

	var join_button := _make_primary_button("Join Lobby")
	join_button.pressed.connect(_on_join_pressed)
	content.add_child(join_button)

	return panel

func _make_card(title_text: String, subtitle_text: String) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.07, 0.07, 0.09, 0.95)
	style.border_color = Color(1, 1, 1, 0.08)
	style.border_width_left = 1
	style.border_width_top = 1
	style.border_width_right = 1
	style.border_width_bottom = 1
	style.corner_radius_top_left = 18
	style.corner_radius_top_right = 18
	style.corner_radius_bottom_left = 18
	style.corner_radius_bottom_right = 18
	style.content_margin_left = 18
	style.content_margin_top = 18
	style.content_margin_right = 18
	style.content_margin_bottom = 18
	panel.add_theme_stylebox_override("panel", style)

	var box := VBoxContainer.new()
	box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	box.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_theme_constant_override("separation", 10)
	panel.add_child(box)

	var title := Label.new()
	title.text = title_text
	title.add_theme_font_size_override("font_size", 24)
	box.add_child(title)

	var subtitle := Label.new()
	subtitle.text = subtitle_text
	subtitle.modulate = Color(0.72, 0.75, 0.80)
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(subtitle)

	var content := VBoxContainer.new()
	content.name = "Content"
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 12)
	box.add_child(content)
	return panel

func _card_content(panel: Control) -> VBoxContainer:
	return panel.find_child("Content", true, false) as VBoxContainer

func _field_with_label(label_text: String, input: LineEdit) -> Control:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	var label := Label.new()
	label.text = label_text
	label.modulate = Color(0.78, 0.81, 0.87)
	box.add_child(label)
	box.add_child(input)
	return box

func _make_input(_name: String, placeholder: String) -> LineEdit:
	var line := LineEdit.new()
	line.placeholder_text = placeholder
	line.custom_minimum_size = Vector2(0, 40)
	line.add_theme_color_override("font_color", Color(0.95, 0.96, 0.98))
	line.add_theme_color_override("font_placeholder_color", Color(0.48, 0.50, 0.56))
	line.clear_button_enabled = true
	return line

func _make_primary_button(text_value: String) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(0, 42)
	return button

func _make_secondary_button(text_value: String) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(0, 42)
	return button

func _refresh_room_list() -> void:
	if rooms_list == null:
		return
	rooms_list.clear()
	_room_rows = []
	for room in LobbyState.discovered_rooms:
		if room is Dictionary:
			var row: Dictionary = room
			_room_rows.append(row)
			var lock_text := "OPEN"
			if bool(row.get("has_password", false)):
				lock_text = "LOCKED"
			var line := "%s  [%d/%d]  %s  %s:%d" % [
				str(row.get("room_name", "Room")),
				int(row.get("players", 0)),
				int(row.get("max_players", 8)),
				lock_text,
				str(row.get("ip", "127.0.0.1")),
				int(row.get("port", 7777))
			]
			rooms_list.add_item(line)
	if _room_rows.is_empty():
		room_hint_label.text = "No LAN rooms found yet. You can still join manually."
	else:
		room_hint_label.text = "Select a room to auto-fill IP/port. Locked rooms require the password from the host."

func _on_room_item_selected(index: int) -> void:
	if index < 0 or index >= _room_rows.size():
		return
	_selected_room = _room_rows[index]
	ip_input.text = str(_selected_room.get("ip", "127.0.0.1"))
	join_port_input.text = str(int(_selected_room.get("port", 7777)))
	var protected_text := "Open"
	if bool(_selected_room.get("has_password", false)):
		protected_text = "Password required"
	room_hint_label.text = "%s hosted by %s — %s" % [
		str(_selected_room.get("room_name", "Room")),
		str(_selected_room.get("host_name", "Host")),
		protected_text
	]

func _on_refresh_rooms_pressed() -> void:
	NetworkManager.start_room_discovery()
	_refresh_room_list()
	status_label.text = "Refreshing LAN rooms..."

func _on_host_pressed() -> void:
	LobbyState.local_player_name = name_input.text.strip_edges()
	var port_value := int(host_port_input.text)
	if NetworkManager.host_lobby(name_input.text, room_input.text, port_value, host_password_input.text):
		get_tree().change_scene_to_file("res://scenes/Lobby.tscn")

func _on_join_pressed() -> void:
	LobbyState.local_player_name = name_input.text.strip_edges()
	if NetworkManager.join_lobby(name_input.text, ip_input.text, int(join_port_input.text), join_password_input.text):
		get_tree().change_scene_to_file("res://scenes/Lobby.tscn")

func _on_join_selected_pressed() -> void:
	if _selected_room.is_empty():
		status_label.text = "Select a room first."
		return
	LobbyState.local_player_name = name_input.text.strip_edges()
	if NetworkManager.join_lobby(name_input.text, str(_selected_room.get("ip", "127.0.0.1")), int(_selected_room.get("port", 7777)), join_password_input.text):
		get_tree().change_scene_to_file("res://scenes/Lobby.tscn")

func _on_open_sandbox_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Game.tscn")

func _on_connection_status_changed(status: String, message: String) -> void:
	status_label.text = "%s — %s" % [status.capitalize(), message]


func _on_back_pressed() -> void:
	get_tree().change_scene_to_file("res://scenes/Main.tscn")
