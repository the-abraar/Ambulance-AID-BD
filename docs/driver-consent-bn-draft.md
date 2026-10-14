# চালকের সম্মতিপত্র (খসড়া)

**DRAFT, not legal advice, needs counsel.** **খসড়া: এটি আইনি পরামর্শ নয়; ব্যবহারের আগে আইনজীবীর পর্যালোচনা প্রয়োজন।**

For counsel: this follows `docs/pilot-plan.md` section 3 and what the code does on 2026-10-14. Check it against the Personal Data Protection Ordinance 2025 (questions 2, 4, 6 and 9 there). An English working translation is below; drivers sign the Bangla text. Items marked TODO need the owner or the operator.

---

এই পাইলটে **[অপারেটরের নাম: OWNER TODO]** অ্যাম্বুলেন্স পাঠানোর কাজে Ambulance-AID-BD নামের একটি সফটওয়্যার পরীক্ষা করছে। আপনি চালক হিসেবে এর অ্যাপ ব্যবহার করলে আপনার কিছু তথ্য সংরক্ষণ করা হবে। স্বাক্ষর করার আগে নিচের কথাগুলো পড়ুন, অথবা কাউকে পড়ে শোনাতে বলুন।

**১. কী তথ্য রাখা হয়**
- আপনার নাম, এবং আপনি দিলে আপনার মোবাইল নম্বর।
- আপনার গাড়ির নিবন্ধন নম্বর।
- মিশন (রোগী আনার কাজ) চলার সময় আপনার ফোনের জিপিএস অবস্থান, যতক্ষণ অ্যাপ খোলা থাকে।
- মিশনের প্রতিটি ধাপ (রওনা, ঘটনাস্থলে পৌঁছানো, রোগী নিয়ে যাওয়া, হাসপাতালে পৌঁছানো, শেষ) কে এবং কখন বদলেছে।
- রোগীর নাম, অসুস্থতা বা ফোন নম্বর এই অ্যাপে রাখার কথা নয়।

**২. কখন অবস্থান নেওয়া হয়**
- শুধু যখন আপনাকে কোনো মিশন দেওয়া আছে এবং অ্যাপ খোলা আছে। মিশন না থাকলে অবস্থান পাঠানো হয় না, এবং সার্ভার তা গ্রহণও করে না।

**৩. কেন নেওয়া হয়**
- কাছের গাড়ি পাঠাতে এবং মিশন সমন্বয় করতে।
- কল আসা থেকে ঘটনাস্থলে পৌঁছাতে কত সময় লাগে, তা মাপতে।

**৪. কে দেখতে পারে**
- অপারেটরের ডিসপ্যাচার ও অ্যাডমিন।
- সার্ভার পরিচালনাকারী (প্রকল্পের মালিক), শুধু রক্ষণাবেক্ষণের জন্য।
- গবেষক বা দাতারা শুধু সমষ্টিগত, পরিচয়হীন তথ্য পাবেন।
- আপনি মোবাইল নম্বর দিলে, মিশনের খবর এসএমএসে পাঠাতে নম্বরটি একটি এসএমএস সেবাদাতাকে (BulkSMSBD) দেওয়া হতে পারে।

**৫. কতদিন রাখা হয়**
- জিপিএস অবস্থান ৯০ দিন পর মুছে ফেলা হয়। ব্যাকআপে তা আরও সর্বোচ্চ ১৪ দিন থাকতে পারে।
- মিশন ও ধাপের রেকর্ড রাখা হয় পাইলট চলাকালীন এবং তারপর **[সময়কাল: COUNSEL TODO]** পর্যন্ত।

**৬. শাস্তির জন্য ব্যবহার নয়**
- এই তথ্য আপনার চাকরি সংক্রান্ত শাস্তি, জরিমানা বা বেতন কাটার জন্য ব্যবহার করা হবে না, যদি না অপারেটর ও চালকরা আগে লিখিতভাবে অন্যরকম একমত হন।

**৭. আপনার ইচ্ছা ও অধিকার**
- অংশ নেওয়া আপনার ইচ্ছা। আপনি না বলতে পারেন, এবং পরে যেকোনো সময় সম্মতি তুলে নিতে পারেন।
- না বললে বা সম্মতি তুলে নিলে আপনার কাজে কী প্রভাব পড়বে: **[অপারেটর পাইলট চুক্তিতে ঠিক করবে: OWNER TODO]**।
- আপনার নিজের তথ্য দেখতে বা মুছে ফেলতে বলতে পারেন। যোগাযোগ: **[নাম ও ফোন: OWNER TODO]**।

**৮. গাড়ি চলার সময়**
- গাড়ি চলার সময় অ্যাপ ব্যবহার করবেন না। থামার পর ধাপ বদলান, অথবা ফোনে ডিসপ্যাচারকে জানান; তিনি আপনার হয়ে তা লিখে রাখবেন।

☐ আমি রাজি  ☐ আমি রাজি নই

চালকের নাম: ____________ স্বাক্ষর বা টিপসই: ____________ তারিখ: ____________

অপারেটরের পক্ষে নাম: ____________ স্বাক্ষর: ____________ তারিখ: ____________

---

## English working translation (for review only)

During this pilot **[operator name: OWNER TODO]** is testing a dispatch software called Ambulance-AID-BD. If you use its app as a driver, some of your data is stored. Read the points below before you sign, or ask someone to read them to you.

1. **What is stored.**
   - Your name and, if you give it, your mobile number.
   - Your vehicle's registration.
   - Your phone's GPS position during a mission while the app is open.
   - Who changed each mission step, and when.
   - Patient names, conditions and phone numbers are not meant to be stored in the app.
2. **When your position is taken.** Only while you have a mission and the app is open. Without a mission, no position is sent, and the server refuses it.
3. **Why.**
   - To send the nearest vehicle and coordinate missions.
   - To measure how long it takes from the call to the scene.
4. **Who can see it.**
   - The operator's dispatchers and admins.
   - The server operator (the project owner), for maintenance only.
   - Researchers and funders see only aggregated, de-identified data.
   - If you give a mobile number, it may be passed to an SMS provider (BulkSMSBD) to text you mission details.
5. **How long.**
   - GPS positions are deleted after 90 days; they may stay up to 14 more days in backups.
   - Mission and step records are kept for the pilot and then **[period: COUNSEL TODO]**.
6. **Not for discipline.** This data will not be used for job discipline, fines or pay cuts, unless the operator and the drivers first agree otherwise in writing.
7. **Your choice and rights.**
   - Taking part is voluntary. You may say no, and you may withdraw consent at any time.
   - The effect of saying no on your work is **[set by the operator in the pilot agreement: OWNER TODO]**.
   - You may ask to see or delete your own data. Contact: **[name and phone: OWNER TODO]**.
8. **While driving.** Do not use the app while the vehicle moves. Change steps when stopped, or tell the dispatcher by phone, who records them for you.

Counsel to confirm:
- Is this consent valid when the employer asks for it?
- Is written or thumbprint consent required, or is logged consent enough?
- Must the notice name the hosting location and the SMS provider's country?
- Is a 90-day ping retention allowed?
