Thinking Questions — Nistula Technical Assessment
Question A — The Immediate Response
The AI’s 3 AM Message:

"Hi, I'm so sorry to hear about the hot water—especially with guests arriving for breakfast so soon. I completely understand how stressful that is. I've just flagged this as a high-priority emergency and pinged our on-call caretaker. Someone will follow up with you within the next 30 minutes to get this sorted out. Please hang tight, we're on it."

Why I chose this wording:
My main thought here was that if someone is texting angrily at 3 AM, they just want to know someone is actually awake and listening. I led with empathy, but more importantly, I gave them a concrete timeframe (30 minutes) rather than a vague "we will look into it," which usually just causes more anxiety. Noticeably, I completely sidestepped the refund request. The AI definitely shouldn't be making financial promises, so focusing entirely on fixing the immediate physical problem felt like the safest boundary.

Question B — The System Design
Here is how I imagine the backend flow kicking off:

Immediate Action (Minute 0):
Once the classifier tags the message as a complaint, it immediately locks the thread so no regular "auto-replies" can fire. It logs the priority and pushes an alert to the operations dashboard. Simultaneously, it sends an SMS/Push notification to the specific caretaker for Villa B1. Since it's a 3 AM emergency, it should also trigger a Slack or WhatsApp ping to the duty manager.

The Fallback (Minute 30):
If nobody hits "acknowledge" on the system alert within 30 minutes, it escalates up the chain (e.g., to the city manager). It should also auto-text the guest again: "We haven't forgotten about you—we are still trying to wake up the right person to get this fixed. We'll update you in 15 mins."

Logging:
Everything—the AI draft, the SMS dispatches, and exactly when a human finally opens the chat—gets written to the agent_actions table. If the guest disputes the charge later, we need a flawless audit trail of exactly how long it took us to respond.

Question C — The Learning
Three identical complaints in two months isn't bad luck; it's a hardware issue.

What the system should do:
First, the classifier should be grouping these issue tags. After the second complaint, a "recurring issue" warning should pop up on the property manager's weekly digest. By the third complaint, the system should bypass humans entirely and auto-generate a maintenance ticket: "Inspect Villa B1 boiler before next check-in." It should also inject a mandatory "check hot water pressure" step into the caretaker’s pre-arrival app for this specific villa.

What I would build to prevent it:
If I had more time, I’d build a "Property Health Score." It would just be a simple script that tracks complaint frequency per category (e.g., Water, AC, WiFi) over a 60-day rolling window. If a property hits a critical threshold, the system automatically blocks out the calendar for any new bookings until a manager clears a maintenance ticket. It basically forces a proactive fix before we end up dealing with a fourth angry 3 AM text!
