// =====================================================
// GemmaFunction – Canonical Test Prompts for LEO CDP
// Optimized for intent detection & function calling
// =====================================================

const SUGGESTIONS_DB = [

  // =========================
  // Weather / External Info
  // =========================
  "Get current weather for New York City",
  "Get current weather for London",
  "Check tomorrow weather forecast for Tokyo",
  "Get current temperature in Paris",
  "Get today weather in Ho Chi Minh City",

  // =========================
  // Campaign Activation (Action-Oriented)
  // =========================
  "Activate segment 'Summer Sale Target' on channel Facebook with message 'Hello, this is our products' immediately",
  "Activate segment 'Summer Sale Target' on channel Zalo OA with message 'Hello, this is our products' immediately",

  // =========================
  // LEO CDP – System & Knowledge
  // =========================
  "Explain LEO CDP data architecture",
  "Show latest user statistics",
  "Generate user engagement report for last month",
  "List all data sources connected to LEO CDP",
  "Show new features in the latest LEO CDP release",
  "Check LEO CDP system status",
  "Troubleshoot data synchronization issues",
  "Explain how to integrate LEO CDP with Shopify",
  "Explain best practices for data segmentation",

  // =========================
  // Customer Profile & Data Ops
  // =========================
  "Create a new customer profile",
  "Export customer data to CSV",
  "Create custom dashboard for sales metrics",
  "Show average user session duration",

  // =========================
  // Segmentation – Read
  // =========================
  "List all customer segments",
  "Show segments created in the last 7 days",
  "Get size of segment 'Inactive Users'",
  "List segments with more than 1000 users",
  "Show top active users",

  // =========================
  // Segmentation – Write
  // =========================
  "Create segment for users who purchased in the last 30 days",
  "Create segment for users located in 'Hanoi'",
  "Create segment for users with high engagement and low purchase frequency",
  "Create segment for users who signed up via referral",
  "Merge segments 'Segment A' and 'Segment B'",
  "Delete segment 'Old Campaign Users'",

  // =========================
  // Segment Export
  // =========================
  "Export segment 'VIP Customers' to CSV",

  // =========================
  // Segment Activation – Messaging
  // =========================
  "Send message 'hello @user' to segment 'new user' via channel 'Zalo'",
  "Send email 'thank you @user' to segment 'user purchased product A'",

];
