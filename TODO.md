# Slack LLM Bot - Future Enhancements

## 📄 File Handling
- [ ] **Read Attachments**
    - [ ] Add `files:read` scope to Slack App.
    - [ ] Update `handle_message` to detect `files` array in events.
    - [ ] Implement file downloading logic using `slack_sdk`.
    - [ ] Implement text extraction for `.txt`, `.csv`, and `.pdf` files.
    - [ ] Integrate extracted text into the LLM prompt context.
- [ ] **Generate and Send Files**
    - [ ] Add `files:write` scope to Slack App.
    - [ ] Create helper function to save LLM responses to temporary files.
    - [ ] Implement `client.files_upload_v2` to send files back to Slack channels.

## 🧠 Memory & Context
- [ ] **Persistent Memory**
    - [ ] Integrate a database (e.g., SQLite or Redis) to store conversation history.
    - [ ] Allow the bot to remember user preferences and previous interactions across threads.
- [ ] **Improved Thread Pagination**
    - [ ] Replace the simple `limit` in `get_thread_messages` with a pagination loop.
    - [ ] Ensure the bot always retrieves the *most recent* messages when a thread exceeds `MAX_THREAD_MESSAGES`.

## ⚙️ Performance & Reliability
- [ ] **Token-based Context Window**
    - [ ] Replace message-count limit with a token-count limit using a tokenizer (e.g., `tiktoken`).
- [ ] **Prompt Templating**
    - [ ] Move system prompts from `app.py` to external template files for easier tuning.
