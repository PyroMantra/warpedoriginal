extends Control

const FALLBACK_CLASS_OPTIONS := [
	{"name":"Vanguard", "affinities":["Steel","Radiance"], "masteries":["Offense","Defense"]},
	{"name":"Arcanist", "affinities":["Flame","Frost","Storm"], "masteries":["Offense","Control"]},
	{"name":"Rogue", "affinities":["Shadow","Poison"], "masteries":["Offense","Utility"]},
	{"name":"Ranger", "affinities":["Wind","Nature"], "masteries":["Offense","Survival"]}
]
const COLOR_OPTIONS := [
	{"id":"yellow","label":"Yellow","hex":"#FACC15"},
	{"id":"blue","label":"Blue","hex":"#3B82F6"},
	{"id":"green","label":"Green","hex":"#22C55E"},
	{"id":"red","label":"Red","hex":"#EF4444"},
	{"id":"purple","label":"Purple","hex":"#A855F7"},
	{"id":"orange","label":"Orange","hex":"#F97316"},
	{"id":"pink","label":"Pink","hex":"#EC4899"},
	{"id":"cyan","label":"Cyan","hex":"#06B6D4"}
]

var _races: Dictionary = {}
var _factions: Array = []
var _class_options: Array = []

var _player_list: VBoxContainer
var _status_label: Label
var _ready_button: Button
var _start_button: Button

var _race_button: OptionButton
var _subtype_button: OptionButton
var _class_button: OptionButton
var _affinity_button: OptionButton
var _mastery_button: OptionButton
var _faction_button: OptionButton
var _color_button: OptionButton
var _preview_text: RichTextLabel

var _chat_log: RichTextLabel
var _chat_input: LineEdit


func _ready() -> void:
	_load_catalogs()
	_build_ui()
	_wire_signals()
	_refresh_all()


func _wire_signals() -> void:
	LobbyState.lobby_updated.connect(_refresh_all)
	LobbyState.chat_updated.connect(_refresh_chat)
	LobbyState.status_changed.connect(_refresh_status)
	NetworkManager.connection_status_changed.connect(_on_connection_status_changed)


func _load_catalogs() -> void:
	var races_json: Variant = _load_json("res://data/lobby_races.json")
	if races_json is Dictionary:
		_races = races_json.get("races", {})

	var factions_json: Variant = _load_json("res://data/lobby_factions.json")
	if factions_json is Dictionary:
		var incoming_factions: Variant = factions_json.get("factions", [])
		if incoming_factions is Array:
			_factions = incoming_factions

	_class_options = _extract_class_options(_load_json("res://data/classes.json"))
	if _class_options.is_empty():
		_class_options = FALLBACK_CLASS_OPTIONS.duplicate(true)


func _load_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return {}
	var text: String = FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(text)
	if parsed == null:
		return {}
	return parsed


func _extract_class_options(data: Variant) -> Array:
	var out: Array = []
	if data is Array:
		for item in data:
			if item is Dictionary:
				_append_class_entry(out, item, str(item.get("name", item.get("id", ""))))
	elif data is Dictionary:
		if data.has("classes") and data["classes"] is Array:
			for item2 in data["classes"]:
				if item2 is Dictionary:
					_append_class_entry(out, item2, str(item2.get("name", item2.get("id", ""))))
		else:
			for key in data.keys():
				var value: Variant = data[key]
				if value is Dictionary:
					_append_class_entry(out, value, str(value.get("name", str(key))))
	return out


func _append_class_entry(out: Array, raw: Dictionary, class_name: String) -> void:
	if class_name == "":
		return
	var affinities: Array = _normalize_affinities(raw.get("affinities", raw.get("affinity_options", raw.get("affinity", []))))
	var masteries: Array = _normalize_masteries(raw)
	if affinities.is_empty():
		affinities = ["Base"]
	if masteries.is_empty():
		masteries = ["General"]
	out.append({
		"name": class_name,
		"affinities": affinities,
		"masteries": masteries
	})


func _normalize_affinities(value: Variant) -> Array:
	var out: Array = []
	if value is Array:
		for item in value:
			if item is Dictionary:
				var n1: String = str(item.get("name", item.get("id", ""))).strip_edges()
				if n1 != "":
					out.append(n1)
			else:
				var s1: String = str(item).strip_edges()
				if s1 != "":
					out.append(s1)
	elif value is String:
		for piece in str(value).split(","):
			var s2: String = piece.strip_edges()
			if s2 != "":
				out.append(s2)
	return out


func _normalize_masteries(raw: Dictionary) -> Array:
	var out: Array = []
	var direct: Variant = raw.get("masteries", raw.get("mastery_options", raw.get("mastery", [])))
	if direct is Array:
		for item in direct:
			var s1: String = str(item).strip_edges()
			if s1 != "":
				out.append(s1)
	elif direct is String:
		for piece in str(direct).split(","):
			var s2: String = piece.strip_edges()
			if s2 != "":
				out.append(s2)
	var primary: String = str(raw.get("masteryPrimary", "")).replace("-", " ").strip_edges().capitalize()
	var secondary: String = str(raw.get("masterySecondary", "")).replace("-", " ").strip_edges().capitalize()
	if primary != "" and not out.has(primary):
		out.append(primary)
	if secondary != "" and not out.has(secondary):
		out.append(secondary)
	return out


func _build_ui() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var root_margin := MarginContainer.new()
	root_margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root_margin.add_theme_constant_override("margin_left", 20)
	root_margin.add_theme_constant_override("margin_top", 20)
	root_margin.add_theme_constant_override("margin_right", 20)
	root_margin.add_theme_constant_override("margin_bottom", 20)
	add_child(root_margin)

	var root_vbox := VBoxContainer.new()
	root_vbox.add_theme_constant_override("separation", 12)
	root_margin.add_child(root_vbox)

	var top_bar := HBoxContainer.new()
	top_bar.add_theme_constant_override("separation", 12)
	root_vbox.add_child(top_bar)

	var title := Label.new()
	title.text = "Lobby"
	title.add_theme_font_size_override("font_size", 28)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top_bar.add_child(title)

	_status_label = Label.new()
	_status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	top_bar.add_child(_status_label)

	var body := HSplitContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root_vbox.add_child(body)

	var left_side := VBoxContainer.new()
	left_side.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left_side.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left_side.custom_minimum_size = Vector2(360, 0)
	left_side.add_theme_constant_override("separation", 12)
	body.add_child(left_side)

	left_side.add_child(_make_panel_title("Players"))
	var players_panel := _make_panel()
	left_side.add_child(players_panel)
	_player_list = VBoxContainer.new()
	_player_list.add_theme_constant_override("separation", 8)
	players_panel.add_child(_player_list)

	var ready_row := HBoxContainer.new()
	ready_row.add_theme_constant_override("separation", 10)
	left_side.add_child(ready_row)

	_ready_button = Button.new()
	_ready_button.text = "Ready / Unready"
	_ready_button.pressed.connect(_on_ready_pressed)
	ready_row.add_child(_ready_button)

	_start_button = Button.new()
	_start_button.text = "Start Game"
	_start_button.pressed.connect(_on_start_pressed)
	ready_row.add_child(_start_button)

	left_side.add_child(_make_panel_title("Lobby Chat"))
	var chat_panel := _make_panel()
	chat_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left_side.add_child(chat_panel)

	_chat_log = RichTextLabel.new()
	_chat_log.fit_content = false
	_chat_log.scroll_active = true
	_chat_log.bbcode_enabled = false
	_chat_log.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_chat_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	chat_panel.add_child(_chat_log)

	var chat_row := HBoxContainer.new()
	chat_row.add_theme_constant_override("separation", 8)
	chat_panel.add_child(chat_row)

	_chat_input = LineEdit.new()
	_chat_input.placeholder_text = "Type a lobby message..."
	_chat_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_chat_input.text_submitted.connect(_on_chat_submitted)
	chat_row.add_child(_chat_input)

	var chat_send := Button.new()
	chat_send.text = "Send"
	chat_send.pressed.connect(_on_chat_send_pressed)
	chat_row.add_child(chat_send)

	var right_side := VBoxContainer.new()
	right_side.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_side.size_flags_vertical = Control.SIZE_EXPAND_FILL
	right_side.add_theme_constant_override("separation", 12)
	body.add_child(right_side)

	right_side.add_child(_make_panel_title("Character Creation"))
	var char_panel := _make_panel()
	right_side.add_child(char_panel)

	var form := GridContainer.new()
	form.columns = 2
	form.add_theme_constant_override("h_separation", 12)
	form.add_theme_constant_override("v_separation", 8)
	char_panel.add_child(form)

	_race_button = _add_labeled_option(form, "Race")
	_subtype_button = _add_labeled_option(form, "Subtype")
	_class_button = _add_labeled_option(form, "Class")
	_affinity_button = _add_labeled_option(form, "Affinity")
	_mastery_button = _add_labeled_option(form, "Mastery")
	_faction_button = _add_labeled_option(form, "Faction")
	_color_button = _add_labeled_option(form, "Color")

	_race_button.item_selected.connect(_on_race_selected)
	_subtype_button.item_selected.connect(_on_preview_changed)
	_class_button.item_selected.connect(_on_class_selected)
	_affinity_button.item_selected.connect(_on_preview_changed)
	_mastery_button.item_selected.connect(_on_preview_changed)
	_faction_button.item_selected.connect(_on_preview_changed)
	_color_button.item_selected.connect(_on_preview_changed)

	var buttons_row := HBoxContainer.new()
	buttons_row.add_theme_constant_override("separation", 8)
	char_panel.add_child(buttons_row)

	var save_char := Button.new()
	save_char.text = "Save Character"
	save_char.pressed.connect(_on_save_character_pressed)
	buttons_row.add_child(save_char)

	var leave_btn := Button.new()
	leave_btn.text = "Leave Lobby"
	leave_btn.pressed.connect(_on_leave_pressed)
	buttons_row.add_child(leave_btn)

	_preview_text = RichTextLabel.new()
	_preview_text.bbcode_enabled = false
	_preview_text.fit_content = false
	_preview_text.custom_minimum_size = Vector2(0, 220)
	_preview_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	char_panel.add_child(_preview_text)


func _make_panel_title(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", 22)
	return label


func _make_panel() -> PanelContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	return panel


func _add_labeled_option(parent: GridContainer, label_text: String) -> OptionButton:
	var label := Label.new()
	label.text = label_text
	parent.add_child(label)
	var opt := OptionButton.new()
	opt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(opt)
	return opt


func _refresh_all() -> void:
	_refresh_status()
	_refresh_player_list()
	_refresh_chat()
	_refresh_character_form()


func _refresh_status() -> void:
	var room_text := LobbyState.room_name
	if room_text == "":
		room_text = "No room"
	_status_label.text = "%s • %s" % [room_text, LobbyState.status_text]


func _refresh_player_list() -> void:
	for child in _player_list.get_children():
		child.queue_free()
	var local_id := LobbyState.get_local_peer_id()
	for key in LobbyState.players.keys():
		var player: Dictionary = LobbyState.players[key]
		var row := VBoxContainer.new()
		row.add_theme_constant_override("separation", 2)
		_player_list.add_child(row)
		var head := Label.new()
		var pname: String = str(player.get("name", "Player"))
		var flags: Array = []
		if bool(player.get("is_host", false)):
			flags.append("Host")
		if bool(player.get("ready", false)):
			flags.append("Ready")
		if int(key) == local_id:
			flags.append("You")
		head.text = pname if flags.is_empty() else "%s [%s]" % [pname, ", ".join(flags)]
		row.add_child(head)
		var character: Dictionary = player.get("character", {})
		var details := Label.new()
		details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		details.modulate = Color(0.78, 0.8, 0.86)
		details.text = _format_character_summary(character)
		row.add_child(details)
	_start_button.visible = multiplayer.is_server()


func _format_character_summary(character: Dictionary) -> String:
	if character.is_empty():
		return "No character selected yet."
	var bits: Array = []
	for key in ["race", "subtype", "class", "affinity", "mastery", "faction", "color"]:
		var value: String = str(character.get(key, "")).strip_edges()
		if value != "":
			bits.append(value)
	return " • ".join(bits)


func _refresh_chat() -> void:
	if _chat_log == null:
		return
	_chat_log.clear()
	for entry in LobbyState.chat_log:
		_chat_log.append_text(str(entry) + "\n")


func _refresh_character_form() -> void:
	_fill_race_button()
	_fill_class_button()
	_fill_faction_button()
	_fill_color_button()
	_apply_local_selection_to_form()
	_update_preview()


func _fill_race_button() -> void:
	var previous := _get_selected_text(_race_button)
	_race_button.clear()
	var race_names: Array = _races.keys()
	race_names.sort()
	for race_name in race_names:
		_race_button.add_item(str(race_name))
	var fallback: String = ""
	if previous != "":
		fallback = previous
	elif not race_names.is_empty():
		fallback = str(race_names[0])
	_select_option_by_text(_race_button, fallback)
	_fill_subtype_button()


func _fill_subtype_button() -> void:
	var previous := _get_selected_text(_subtype_button)
	_subtype_button.clear()
	var race_name := _get_selected_text(_race_button)
	if race_name == "" or not _races.has(race_name):
		return
	var subtypes: Array = _races[race_name].get("subtypes", [])
	for entry in subtypes:
		_subtype_button.add_item(str(entry.get("subtype", "")))
	var fallback: String = previous
	if fallback == "" and _subtype_button.item_count > 0:
		fallback = _subtype_button.get_item_text(0)
	_select_option_by_text(_subtype_button, fallback)


func _fill_class_button() -> void:
	var previous_class := _get_selected_text(_class_button)
	_class_button.clear()
	for entry in _class_options:
		_class_button.add_item(str(entry.get("name", "")))
	var fallback: String = previous_class
	if fallback == "" and _class_button.item_count > 0:
		fallback = _class_button.get_item_text(0)
	_select_option_by_text(_class_button, fallback)
	_fill_affinity_and_mastery()


func _fill_affinity_and_mastery() -> void:
	var previous_affinity := _get_selected_text(_affinity_button)
	var previous_mastery := _get_selected_text(_mastery_button)
	_affinity_button.clear()
	_mastery_button.clear()
	var class_name := _get_selected_text(_class_button)
	for entry in _class_options:
		if str(entry.get("name", "")) == class_name:
			for affinity in entry.get("affinities", []):
				_affinity_button.add_item(str(affinity))
			for mastery in entry.get("masteries", []):
				_mastery_button.add_item(str(mastery))
			break
	var affinity_fallback: String = previous_affinity
	if affinity_fallback == "" and _affinity_button.item_count > 0:
		affinity_fallback = _affinity_button.get_item_text(0)
	var mastery_fallback: String = previous_mastery
	if mastery_fallback == "" and _mastery_button.item_count > 0:
		mastery_fallback = _mastery_button.get_item_text(0)
	_select_option_by_text(_affinity_button, affinity_fallback)
	_select_option_by_text(_mastery_button, mastery_fallback)


func _fill_faction_button() -> void:
	var previous := _get_selected_text(_faction_button)
	_faction_button.clear()
	for entry in _factions:
		_faction_button.add_item(str(entry.get("name", "")))
	var fallback: String = previous
	if fallback == "" and _faction_button.item_count > 0:
		fallback = _faction_button.get_item_text(0)
	_select_option_by_text(_faction_button, fallback)


func _fill_color_button() -> void:
	var previous := _get_selected_metadata(_color_button)
	_color_button.clear()
	var taken := LobbyState.get_taken_colors(LobbyState.get_local_peer_id())
	for idx in range(COLOR_OPTIONS.size()):
		var entry: Dictionary = COLOR_OPTIONS[idx]
		var color_id: String = str(entry.get("id", ""))
		var label: String = str(entry.get("label", color_id))
		_color_button.add_item(label)
		_color_button.set_item_metadata(idx, color_id)
		_color_button.set_item_disabled(idx, taken.has(color_id))
	var local_player: Dictionary = LobbyState.get_local_player()
	var local_char: Dictionary = local_player.get("character", {})
	var desired: String = str(local_char.get("color", previous))
	if desired == "":
		for entry2 in COLOR_OPTIONS:
			var cid: String = str(entry2.get("id", ""))
			if not taken.has(cid):
				desired = cid
				break
	_select_option_by_metadata(_color_button, desired)


func _apply_local_selection_to_form() -> void:
	var local_player: Dictionary = LobbyState.get_local_player()
	var local_char: Dictionary = local_player.get("character", {})
	if local_char.is_empty():
		return
	_select_option_by_text(_race_button, str(local_char.get("race", "")))
	_fill_subtype_button()
	_select_option_by_text(_subtype_button, str(local_char.get("subtype", "")))
	_select_option_by_text(_class_button, str(local_char.get("class", "")))
	_fill_affinity_and_mastery()
	_select_option_by_text(_affinity_button, str(local_char.get("affinity", "")))
	_select_option_by_text(_mastery_button, str(local_char.get("mastery", "")))
	_select_option_by_text(_faction_button, str(local_char.get("faction", "")))
	_select_option_by_metadata(_color_button, str(local_char.get("color", "")))


func _update_preview() -> void:
	var race_name := _get_selected_text(_race_button)
	var subtype_name := _get_selected_text(_subtype_button)
	var subtype_data := _find_subtype_data(race_name, subtype_name)
	var lines: Array = []
	lines.append("Race: %s" % race_name)
	lines.append("Subtype: %s" % subtype_name)
	lines.append("Class: %s" % _get_selected_text(_class_button))
	lines.append("Affinity: %s" % _get_selected_text(_affinity_button))
	lines.append("Mastery: %s" % _get_selected_text(_mastery_button))
	lines.append("Faction: %s" % _get_selected_text(_faction_button))
	lines.append("Color: %s" % _get_selected_metadata(_color_button))
	lines.append("")
	if not subtype_data.is_empty():
		lines.append("HP %d | Mana %d | DEF %d | DISP %d" % [
			int(subtype_data.get("health", 0)),
			int(subtype_data.get("mana", 0)),
			int(subtype_data.get("defense", 0)),
			int(subtype_data.get("dispersion", 0))
		])
		lines.append("STR %d | DEX %d | POW %d | STA %d | FORT %d" % [
			int(subtype_data.get("strength", 0)),
			int(subtype_data.get("dexterity", 0)),
			int(subtype_data.get("power", 0)),
			int(subtype_data.get("stamina", 0)),
			int(subtype_data.get("fortitude", 0))
		])
		lines.append("")
		lines.append("Conditions: %s" % str(subtype_data.get("conditions", "None")))
		lines.append("")
		lines.append("Subtype: %s" % str(subtype_data.get("subtype_description", "")))
	_preview_text.clear()
	_preview_text.text = "\n".join(lines)


func _find_subtype_data(race_name: String, subtype_name: String) -> Dictionary:
	if not _races.has(race_name):
		return {}
	for entry in _races[race_name].get("subtypes", []):
		if str(entry.get("subtype", "")) == subtype_name:
			return entry
	return {}


func _get_selected_text(button: OptionButton) -> String:
	if button == null or button.item_count == 0 or button.selected < 0:
		return ""
	return button.get_item_text(button.selected)


func _get_selected_metadata(button: OptionButton) -> String:
	if button == null or button.item_count == 0 or button.selected < 0:
		return ""
	return str(button.get_item_metadata(button.selected))


func _select_option_by_text(button: OptionButton, value: String) -> void:
	if button == null:
		return
	for idx in range(button.item_count):
		if button.get_item_text(idx) == value:
			button.select(idx)
			return
	if button.item_count > 0:
		button.select(0)


func _select_option_by_metadata(button: OptionButton, value: String) -> void:
	if button == null:
		return
	for idx in range(button.item_count):
		if str(button.get_item_metadata(idx)) == value:
			button.select(idx)
			return
	if button.item_count > 0:
		button.select(0)


func _on_race_selected(_idx: int) -> void:
	_fill_subtype_button()
	_update_preview()


func _on_class_selected(_idx: int) -> void:
	_fill_affinity_and_mastery()
	_update_preview()


func _on_preview_changed(_idx: int) -> void:
	_update_preview()


func _on_save_character_pressed() -> void:
	var payload := {
		"race": _get_selected_text(_race_button),
		"subtype": _get_selected_text(_subtype_button),
		"class": _get_selected_text(_class_button),
		"affinity": _get_selected_text(_affinity_button),
		"mastery": _get_selected_text(_mastery_button),
		"faction": _get_selected_text(_faction_button),
		"color": _get_selected_metadata(_color_button)
	}
	NetworkManager.set_character_payload(payload)
	LobbyState.set_status("Character saved.")


func _on_ready_pressed() -> void:
	var local_player: Dictionary = LobbyState.get_local_player()
	var current_ready: bool = bool(local_player.get("ready", false))
	NetworkManager.set_ready(not current_ready)


func _on_start_pressed() -> void:
	NetworkManager.start_game()


func _on_chat_submitted(text: String) -> void:
	_send_chat(text)


func _on_chat_send_pressed() -> void:
	_send_chat(_chat_input.text)


func _send_chat(text: String) -> void:
	var clean: String = text.strip_edges()
	if clean == "":
		return
	NetworkManager.send_chat_message(clean)
	_chat_input.clear()


func _on_leave_pressed() -> void:
	NetworkManager.disconnect_from_lobby()
	if ResourceLoader.exists("res://scenes/HomeMenu.tscn"):
		get_tree().change_scene_to_file("res://scenes/HomeMenu.tscn")


func _on_connection_status_changed(_status: String, _message: String) -> void:
	_refresh_status()
