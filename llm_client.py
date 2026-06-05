import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.model = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
        
        # Check if we are running in mock mode
        self.is_mock = (
            not self.api_key or 
            self.api_key == "your-openrouter-api-key" or 
            self.api_key.strip() == ""
        )
        
        if self.is_mock:
            logger.warning("OPENROUTER_API_KEY is not configured. Running in MOCK Mode.")
            self.client = None
        else:
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
            )

    def _call_api(self, messages, response_json=False):
        if self.is_mock:
            raise ValueError("API calls are disabled in mock mode")

        try:
            extra_body = {}
            if response_json:
                # OpenRouter supports JSON format for most modern models
                response_format = {"type": "json_object"}
            else:
                response_format = None

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_format,
                extra_body=extra_body,
                temperature=0.1, # low temperature for decision precision
                max_tokens=1024  # limit token usage and avoid OpenRouter credit estimation blocks
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error calling LLM API: {e}")
            raise e

    def detect_decision(self, message: str, context: str = "") -> dict:
        """
        Analyzes a message and its thread/channel context to detect if a decision was made.
        Returns a dictionary containing the structured decision info or is_decision = False.
        """
        if self.is_mock:
            # Mock reasoning for demo
            msg_lower = message.lower()
            if any(term in msg_lower for term in ["postgresql for v1", "let's go with postgresql", "use postgresql", "final then"]):
                return {
                    "is_decision": True,
                    "title": "Use PostgreSQL for v1",
                    "summary": "The team agreed to use PostgreSQL for version 1 of the application.",
                    "reason": "PostgreSQL is safer because the project data model is structured.",
                    "participants": ["Ayush", "Priya", "Rahul"],
                    "confidence": 0.95,
                    "needs_confirmation": True
                }
            return {
                "is_decision": False,
                "title": "",
                "summary": "",
                "reason": "",
                "participants": [],
                "confidence": 0.0,
                "needs_confirmation": False
            }

        system_prompt = (
            "You are AlignOS, an AI decision detector. Analyze the message and surrounding context.\n"
            "Determine if a final decision was reached by the team. A decision is defined as a point where the team "
            "resolves a choice, commits to an action, or finalizes a plan (e.g., 'let's use X', 'deadline is set to Y', 'we agreed on Z').\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            "  \"is_decision\": bool,\n"
            "  \"title\": \"Short, action-oriented title of the decision (e.g., Use PostgreSQL for Database)\",\n"
            "  \"summary\": \"Brief summary of what was decided\",\n"
            "  \"reason\": \"Reasoning/rationale given for this choice, if any\",\n"
            "  \"participants\": [\"List of usernames involved in the decision\"],\n"
            "  \"confidence\": float (between 0.0 and 1.0 representing your detection confidence),\n"
            "  \"needs_confirmation\": bool (should be true if it was an informal consensus that needs validation)\n"
            "}"
        )

        user_content = f"Message: {message}\n"
        if context:
            user_content += f"Surrounding Conversation Context:\n{context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            raw_response = self._call_api(messages, response_json=True)
            return json.loads(raw_response)
        except Exception:
            # Safe fallback
            return {"is_decision": False, "title": "", "summary": "", "reason": "", "participants": [], "confidence": 0.0, "needs_confirmation": False}

    def detect_conflict(self, new_message: str, confirmed_memories: list, recent_context: str = "") -> dict:
        """
        Compares a new message against confirmed memories to see if it contradicts them.
        """
        if self.is_mock:
            msg_lower = new_message.lower()
            if "mongodb" in msg_lower:
                # Find if we have a postgresql decision in confirmed memory
                for mem in confirmed_memories:
                    if "postgresql" in mem.get("summary", "").lower() or "postgresql" in mem.get("title", "").lower():
                        return {
                            "is_conflict": True,
                            "conflict_type": "technology_choice",
                            "severity": "medium",
                            "explanation": f"The message mentions MongoDB setup, which directly contradicts the confirmed decision: '{mem.get('title')}' ({mem.get('summary')}).",
                            "conflicting_memory_id": mem.get("id"),
                            "recommended_action": "remind_decision"
                        }
            return {
                "is_conflict": False,
                "conflict_type": "",
                "severity": "",
                "explanation": "",
                "conflicting_memory_id": None,
                "recommended_action": ""
            }

        # Format memories for prompt
        memories_str = ""
        for mem in confirmed_memories:
            memories_str += f"- ID: {mem.get('id')} | Title: {mem.get('title')} | Summary: {mem.get('summary')} | Reason: {mem.get('reason')}\n"

        system_prompt = (
            "You are AlignOS, an AI conflict detector. Your job is to identify when a new message contradicts "
            "previously confirmed team decisions or project memory items.\n"
            "Review the list of confirmed memories and the new message. Decide if there is a conflict.\n"
            "A conflict is a clear contradiction of a decision (e.g. decision is 'Use Postgres', new message is 'I am installing Mongo'). "
            "Do not alert for casual brainstorming, but do alert for actionable statements that violate confirmed memory.\n"
            "Respond ONLY with a JSON object in this schema:\n"
            "{\n"
            "  \"is_conflict\": bool,\n"
            "  \"conflict_type\": \"e.g., technology_choice, timeline, ownership, scope\",\n"
            "  \"severity\": \"low\", \"medium\", or \"high\",\n"
            "  \"explanation\": \"Clear explanation of the conflict (e.g., 'New message mentions MongoDB setup, which contradicts confirmed memory PostgreSQL for v1')\",\n"
            "  \"conflicting_memory_id\": int (the ID of the memory item that is being contradicted, or null if none),\n"
            "  \"recommended_action\": \"remind_decision\", \"reopen_decision\", or \"ignore\"\n"
            "}"
        )

        user_content = (
            f"Confirmed Memories:\n{memories_str}\n"
            f"New Message: {new_message}\n"
        )
        if recent_context:
            user_content += f"Recent context (fresh conversation): {recent_context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            raw_response = self._call_api(messages, response_json=True)
            return json.loads(raw_response)
        except Exception:
            return {"is_conflict": False, "conflict_type": "", "severity": "", "explanation": "", "conflicting_memory_id": None, "recommended_action": ""}

    def verify_evidence(self, proposed_answer: str, evidence_messages: list, memory_items: list) -> dict:
        """
        Verifies if a proposed answer is supported, partially supported, or contradicted by evidence.
        """
        if self.is_mock:
            # Simple offline mock verification
            if "postgresql" in proposed_answer.lower():
                return {
                    "support_level": "SUPPORTED",
                    "confidence": 0.95,
                    "contradictions": [],
                    "missing_evidence": [],
                    "safe_to_answer": True
                }
            return {
                "support_level": "INSUFFICIENT_EVIDENCE",
                "confidence": 0.2,
                "contradictions": [],
                "missing_evidence": ["Pricing was not finalized in the conversation history."],
                "safe_to_answer": False
            }

        evidence_str = "\n".join([f"- User {m.get('slack_user_id')}: {m.get('snippet')}" for m in evidence_messages])
        memories_str = "\n".join([f"- {m.get('title')}: {m.get('summary')}" for m in memory_items])

        system_prompt = (
            "You are AlignOS, an AI evidence verifier. Your job is to check if a proposed answer is supported "
            "by the retrieved Slack messages (evidence) and confirmed memory.\n"
            "Classify the support level as:\n"
            "- SUPPORTED: The proposed answer is fully verified and backed by the evidence.\n"
            "- PARTIALLY_SUPPORTED: The answer has some support, but makes some unsupported assertions.\n"
            "- CONFLICTING: The evidence directly contradicts what the proposed answer says.\n"
            "- INSUFFICIENT_EVIDENCE: There isn't enough information in the provided context to support this answer.\n"
            "Respond ONLY with a JSON object in this schema:\n"
            "{\n"
            "  \"support_level\": \"SUPPORTED\" | \"PARTIALLY_SUPPORTED\" | \"CONFLICTING\" | \"INSUFFICIENT_EVIDENCE\",\n"
            "  \"confidence\": float (0.0 to 1.0),\n"
            "  \"contradictions\": [\"list of contradicting points, if any\"],\n"
            "  \"missing_evidence\": [\"list of missing context points required to make the answer fully supported\"],\n"
            "  \"safe_to_answer\": bool (should be true only if SUPPORTED or PARTIALLY_SUPPORTED and confidence > 0.6)\n"
            "}"
        )

        user_content = (
            f"Proposed Answer: {proposed_answer}\n\n"
            f"Retrieved Slack Evidence Messages:\n{evidence_str}\n\n"
            f"Confirmed Memory Database Items:\n{memories_str}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            raw_response = self._call_api(messages, response_json=True)
            return json.loads(raw_response)
        except Exception:
            return {"support_level": "INSUFFICIENT_EVIDENCE", "confidence": 0.0, "contradictions": [], "missing_evidence": [], "safe_to_answer": False}

    def generate_answer(self, question: str, confirmed_memories: list, live_evidence: list) -> str:
        """
        Generates an answer grounding it strictly on evidence and memories, avoiding hallucinations.
        """
        if self.is_mock:
            q_lower = question.lower()
            if "database" in q_lower or "postgresql" in q_lower:
                return (
                    "**Confirmed decision:** PostgreSQL for v1.\n"
                    "**Reasoning:** Priya noted that our data model is structured, which makes PostgreSQL a safer choice. "
                    "Ayush finalized the decision and Rahul agreed.\n"
                    "**Confidence:** High (0.95)\n"
                    "**Source:** Confirmed memory + Slack discussion"
                )
            # Default mock refusal
            return (
                "I could not find enough evidence in the memory or conversation history to verify this. "
                "I found discussion about possible options, but no confirmed decision.\n"
                "Would you like me to start a decision thread?"
            )

        memories_str = "\n".join([f"- [Confirmed Memory] {m.get('title')}: {m.get('summary')} (Reason: {m.get('reason')})" for m in confirmed_memories])
        evidence_str = "\n".join([f"- [Live Slack Message] {m.get('slack_user_id', 'User')}: {m.get('snippet', m.get('text', ''))}" for m in live_evidence])

        system_prompt = (
            "You are AlignOS, the Slack-native project memory intelligence layer.\n"
            "Answer the user's question using ONLY the provided Confirmed Memories and Live Slack Messages.\n"
            "Follow these rules strictly:\n"
            "1. Ground your answer completely in the context. Do not make up facts or extrapolate.\n"
            "2. If the context does not contain enough information to answer, state that you cannot find sufficient evidence and "
            "explain what you found instead (e.g. 'I found discussions about pricing but no confirmed decision').\n"
            "3. State your sources (e.g. whether it came from confirmed memory, live discussion, or both).\n"
            "4. Add a confidence level (High/Medium/Low) based on how well the evidence supports the answer.\n"
            "5. Avoid conversational fluff. Keep it skimmable and professional for a Slack thread."
        )

        user_content = (
            f"Question: {question}\n\n"
            f"Context:\n"
            f"--- CONFIRMED MEMORIES ---\n{memories_str}\n\n"
            f"--- LIVE SLACK DISCUSSION ---\n{evidence_str}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            return self._call_api(messages, response_json=False)
        except Exception:
            return "Sorry, I encountered an error checking my memory database."

    def generate_project_summary(self, channel_id: str, decisions: list, tasks: list, conflicts: list) -> str:
        """
        Generates a skimmable project memory summary card content.
        """
        if self.is_mock:
            return (
                "📊 *AlignOS Project Memory Summary*\n\n"
                "*Current Goal:* Build AlignOS MVP for Slack hackathon.\n\n"
                "*Confirmed Decisions:*\n"
                "• *Use PostgreSQL for v1* - Safer because data is structured (confirmed by Ayush).\n"
                "• *Slack-First MVP* - No separate web dashboard needed.\n\n"
                "*Open Tasks:*\n"
                "• Set up Slack event endpoint (Owner: Rahul)\n"
                "• Build MCP decision tools (Owner: Ayush)\n\n"
                "*Recent Conflicts:*\n"
                "• ⚠️ MongoDB setup mentioned by Rahul contradicts PostgreSQL decision.\n\n"
                "*Unresolved Questions:*\n"
                "• Should we add GitHub integration for the demo?"
            )

        decisions_str = "\n".join([f"• *{d.get('title')}* - {d.get('summary')} (Reason: {d.get('reason')})" for d in decisions]) or "None confirmed yet."
        tasks_str = "\n".join([f"• {t.get('title')} (Owner: {t.get('owner_user_id', 'Unassigned')}) - *{t.get('status')}*" for t in tasks]) or "No active tasks."
        conflicts_str = "\n".join([f"• ⚠️ *{c.get('conflict_type')} conflict*: {c.get('explanation')} (*{c.get('status')}*)" for c in conflicts]) or "No open conflicts."

        system_prompt = (
            "You are AlignOS, summarizing the project state.\n"
            "Format a clean, professional Slack message that provides a project summary based on database records.\n"
            "Organize by sections: Confirmed Decisions, Active Tasks, Recent Conflicts, and Blockers/Questions.\n"
            "Use Slack Markdown formatting (*bold*, _italics_, • bullet points).\n"
            "Keep it highly skimmable and concise."
        )

        user_content = (
            f"Decisions:\n{decisions_str}\n\n"
            f"Tasks:\n{tasks_str}\n\n"
            f"Conflicts:\n{conflicts_str}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            return self._call_api(messages, response_json=False)
        except Exception:
            return "Error generating project memory summary."
