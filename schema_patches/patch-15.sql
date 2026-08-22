-- patch-15: focus_area on user_state for plan_roadmap_focus
ALTER TABLE user_state ADD COLUMN focus_area TEXT;
