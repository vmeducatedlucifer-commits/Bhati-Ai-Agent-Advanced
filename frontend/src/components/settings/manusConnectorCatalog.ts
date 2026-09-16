export type ManusConnectorCategory = "productivity" | "automation" | "development" | "ai" | "growth" | "media" | "data" | "commerce" | "browser";

export interface ManusConnectorCatalogItem {
  id: string;
  name: string;
  category: ManusConnectorCategory;
  auth: "OAuth 2.0" | "API key" | "MCP";
  description: string;
  implemented: boolean;
}

/**
 * Publicly documented Manus API connector catalog (checked 2026-09-15).
 * IDs are kept as stable provider references for future task-level connector selection.
 * `implemented` means Rawal has a verified direct connector client today; catalog-only
 * entries remain discoverable and are routed through the MCP/custom-server setup flow.
 */
const RAW_MANUS_CONNECTOR_CATALOG: Array<[string, string, ManusConnectorCategory, ManusConnectorCatalogItem["auth"], string, boolean]> = [
  ["001e6a99-5585-4b3e-b8cb-533fe24d7788", "Slack", "productivity", "OAuth 2.0", "Team messages, channels, and notifications", true],
  ["9c27c684-2f4f-4d33-8fcf-51664ea15c00", "Notion", "productivity", "API key", "Pages, databases, and workspace context", true],
  ["433d2fe0-e56d-42b2-8625-9996eab0bb1d", "Zapier", "automation", "OAuth 2.0", "Connect thousands of apps through automations", false],
  ["219459c8-f04d-41af-9a0d-6f9159bf9205", "Asana", "productivity", "OAuth 2.0", "Projects, tasks, and team delivery", false],
  ["40ecbda4-5aaf-4e95-bf54-679299ea1c19", "monday.com", "productivity", "OAuth 2.0", "Boards, items, and team workflows", false],
  ["f8405590-5602-4fee-bfd6-f221623e6f72", "Make", "automation", "OAuth 2.0", "Scenario automation and orchestration", false],
  ["982c169d-0c89-4dbd-95fd-30b49cc2f71e", "Linear", "development", "API key", "Issues, projects, and engineering cycles", true],
  ["74d21d62-2ba7-4840-a918-c8327db5c711", "Atlassian", "development", "OAuth 2.0", "Jira, Confluence, and team knowledge", false],
  ["e08b2bda-a4a6-488a-b397-c72f0923bdf4", "ClickUp", "productivity", "OAuth 2.0", "Tasks, docs, and project spaces", false],
  ["942ea72c-09f6-46f0-b4b3-f9890a6edbc5", "OpenAI", "ai", "API key", "Models and AI-powered actions", false],
  ["84ab78ef-139c-48ff-acd4-cba718b8a484", "Supabase", "development", "API key", "Database, auth, storage, and edge functions", false],
  ["a50c5d31-af5e-4e01-a992-057663a7ee1f", "Vercel", "development", "API key", "Deploy and manage web projects", true],
  ["815b5a30-463e-4662-8da7-081e3b5dfc7d", "Anthropic", "ai", "API key", "Claude models and AI workflows", false],
  ["9a0c8590-c0d9-498b-9b3d-bd0df0dbc134", "Neon", "development", "API key", "Serverless Postgres databases", false],
  ["4c55391d-38ea-4a36-a670-a59a1c7680cb", "Prisma Postgres", "development", "API key", "Managed Postgres for applications", false],
  ["838d5e1c-7dd4-4782-9429-c459126707c7", "Sentry", "development", "API key", "Errors, traces, and performance monitoring", false],
  ["bdfa81ea-c0ca-4022-bba1-805c48b583c1", "Hugging Face", "ai", "API key", "Models, datasets, and Spaces", true],
  ["2a574fdc-89ab-4ad7-b334-e2c156201b6f", "Perplexity", "ai", "API key", "Search-grounded AI answers", false],
  ["bbec86c8-29f6-4149-9bba-d5c66bd6a701", "Cohere", "ai", "API key", "Language and retrieval models", false],
  ["b389f747-6221-41aa-9dbb-732a97a02ea6", "HubSpot", "growth", "OAuth 2.0", "CRM, deals, and sales activity", false],
  ["73f5f556-978a-4f8a-85b3-ef2eec4473e5", "Intercom", "growth", "OAuth 2.0", "Customer conversations and support", false],
  ["23181678-c628-4c53-9a77-36778a36bbe5", "ElevenLabs", "media", "API key", "Voice generation and speech tools", false],
  ["29986b52-7cbb-4d5e-9263-dd0abacaf28d", "Stripe", "commerce", "API key", "Payments, customers, and revenue", true],
  ["491cde51-195c-4e72-96ea-8d80557c3b58", "Grok", "ai", "API key", "xAI language models", false],
  ["e90398ef-c17d-46e8-86d6-0bd98642cbbb", "PayPal for Business", "commerce", "OAuth 2.0", "Payments and merchant operations", false],
  ["c55a74cf-a236-4eda-8885-365d336cae4b", "OpenRouter", "ai", "API key", "Multi-provider model routing", false],
  ["a104e1ac-73e5-482f-96e6-8b95f4756f27", "RevenueCat", "commerce", "API key", "Subscriptions and in-app revenue", false],
  ["305b3b49-32ce-4b2b-a355-3492fe85d17f", "Ahrefs", "growth", "API key", "SEO research and site intelligence", false],
  ["9b37aa72-4089-4f25-b774-122860ba61fa", "Close", "growth", "API key", "Sales CRM and calling workflows", false],
  ["7c635638-0b9f-40f4-b5c8-6f2762416d79", "Xero", "commerce", "OAuth 2.0", "Accounting and financial reporting", false],
  ["700c656f-b4a4-4e39-a886-a20782d99b6f", "Similarweb", "growth", "API key", "Market and web traffic intelligence", false],
  ["2918a878-d84d-47af-94ce-4967b72506f5", "Dropbox", "productivity", "OAuth 2.0", "Cloud files and team folders", false],
  ["be268223-40b2-4f3c-a907-c12eb1699283", "My Browser", "browser", "MCP", "Browser-based authenticated tasks", false],
  ["5c305236-d14e-43f7-93ff-b288afd26f09", "Flux", "media", "API key", "Image generation workflows", false],
  ["d669ca60-22cf-4e16-93d4-845071f9216c", "Airtable", "productivity", "OAuth 2.0", "Tables, records, and lightweight databases", false],
  ["888c4ef0-4ed7-4f8b-ade0-55a86fc531dc", "Dify", "ai", "API key", "AI applications and workflow orchestration", false],
  ["99474cab-58bf-47ae-af0e-43c156703be9", "Kling", "media", "API key", "Video generation workflows", false],
  ["9444d960-ab7e-450f-9cb9-b9467fb0adda", "Gmail", "productivity", "OAuth 2.0", "Email search, drafting, and triage", false],
  ["dd5abf31-7ad3-4c0b-9b9a-f0a576645baf", "Google Calendar", "productivity", "OAuth 2.0", "Events, scheduling, and availability", false],
  ["3db6c7f4-0ce6-4b76-baad-c6e3c4882acd", "Tripo AI", "media", "API key", "3D asset generation", false],
  ["119e6b13-c2e3-48db-b568-f82191de6b4e", "Cloudflare", "development", "API key", "Domains, workers, and edge infrastructure", false],
  ["f8900a57-4bd7-46cc-83a3-5ebd2420a817", "Google Drive", "productivity", "OAuth 2.0", "Files, folders, and shared drives", false],
  ["89dac2c3-74d0-4f94-86d1-0ee6c4566193", "PostHog", "growth", "API key", "Product analytics and feature flags", false],
  ["356d5bc1-fb9f-4fa1-babb-05039dc09d63", "Playwright", "browser", "MCP", "Browser automation and testing", false],
  ["d6b4170a-4001-450d-823a-287dfd9716a7", "n8n", "automation", "OAuth 2.0", "Workflow automation and webhooks", false],
  ["45d392d3-d308-4cdb-8a2d-5d249bcec594", "Jam", "browser", "OAuth 2.0", "Bug reports and screen recordings", false],
  ["d485c6dd-4939-40fb-9c4a-c9821971468b", "Outlook Mail", "productivity", "OAuth 2.0", "Microsoft email and inbox workflows", false],
  ["c63d86db-4c98-483a-af0c-f94721d7f2a5", "Canva", "media", "OAuth 2.0", "Design assets and visual content", false],
  ["fb659ead-d821-40cc-ab35-1cad9af13649", "Stripe API", "commerce", "API key", "Advanced Stripe API access", false],
  ["1d489fb9-0601-4ea7-9942-b866657178c1", "Webflow", "development", "OAuth 2.0", "Sites, CMS, and publishing", false],
  ["4bca3029-d276-4644-898d-578a723361b2", "Outlook Calendar", "productivity", "OAuth 2.0", "Microsoft calendar and scheduling", false],
  ["80bca437-287e-4407-adf0-1a0b298528e5", "Cloudflare API", "development", "API key", "Cloudflare API operations", false],
  ["86a04f98-35cf-4099-9044-ab851a473cf5", "Supabase API", "development", "API key", "Supabase API operations", false],
  ["d0fa4acf-7cf6-4402-bd84-82a850342a79", "Wix", "development", "OAuth 2.0", "Website content and publishing", false],
  ["0d21d573-1ee0-484b-8e91-aed6534dbb19", "Granola", "productivity", "OAuth 2.0", "Meeting notes and summaries", false],
  ["1b62b634-58e9-4b49-b327-339cc5aaeaf5", "Fireflies", "productivity", "API key", "Meeting transcripts and insights", false],
  ["f7bbbff0-61fe-458b-975a-3e2f6a91269c", "tl;dv", "productivity", "OAuth 2.0", "Meeting recordings and notes", false],
  ["abb9ed36-e693-44ab-be3d-1f5c3bb02294", "Firecrawl", "browser", "API key", "Web crawling and extraction", false],
  ["2900673c-afaa-4dfa-901d-00a6b3f7275e", "Todoist", "productivity", "OAuth 2.0", "Tasks and personal productivity", false],
  ["376008de-cd2a-4bfb-93aa-2652b8585c8e", "Polygon.io", "data", "API key", "Market and financial data", false],
  ["d1edd2c7-392f-4132-bcf7-7f86efe1db54", "ZoomInfo", "growth", "API key", "B2B intelligence and prospecting", false],
  ["331ff697-8348-4ed7-a596-7df98740fc1f", "Mailchimp Marketing", "growth", "API key", "Email marketing and audiences", false],
  ["bb2a05d0-d728-48eb-b796-9b71e4f9c9ee", "Apollo", "growth", "API key", "Prospecting and sales intelligence", false],
  ["9fe14dac-4288-4371-91a8-86a36051a865", "Metabase", "data", "API key", "Business intelligence and dashboards", false],
  ["3cb9f78b-b53a-49ef-b65e-b56eeddd641d", "Explorium", "data", "API key", "Data enrichment and signals", false],
  ["f7f15fe8-15cf-4fb9-a546-720f16dcf5e6", "Serena", "development", "MCP", "Code intelligence and engineering tools", false],
  ["c8298c13-6d9a-4847-9f1f-1523952fddbd", "JSONBin.io", "data", "API key", "Simple hosted JSON storage", false],
  ["c183add9-c22c-4199-b7f2-d885571afa3a", "HeyGen", "media", "API key", "Avatar and video generation", false],
  ["bbb0df76-66bd-4a24-ae4f-2aac4750d90b", "GitHub", "development", "OAuth 2.0", "Repositories, issues, and pull requests", true],
  ["cf19c9d0-5f91-4e7a-af04-593febb5c80c", "Apify", "browser", "API key", "Actors, crawlers, and web automation", false],
  ["fd15db79-1975-4579-8d0a-cbc72b28fac1", "Sales AI Assistant", "growth", "MCP", "Sales research and assistance", false],
  ["bc3176ba-efd9-427d-8455-fe64483e894e", "Spend", "commerce", "API key", "Spend management and finance workflows", false],
  ["7f5d51a1-c7b7-442f-a99b-b176cc71a8e8", "Quick Experiments", "development", "MCP", "Rapid product experiments", false],
  ["9777f7bd-4ca3-431a-98d6-a7ed5221dd81", "Instagram Creator Marketplace", "growth", "OAuth 2.0", "Creator discovery and campaign workflows", false],
];

export const MANUS_CONNECTOR_CATALOG: ManusConnectorCatalogItem[] = RAW_MANUS_CONNECTOR_CATALOG.map(([id, name, category, auth, description, implemented]) => ({ id, name, category, auth, description, implemented }));

export const IMPLEMENTED_MANUS_CONNECTOR_NAMES = new Set(MANUS_CONNECTOR_CATALOG.filter((item) => item.implemented).map((item) => item.name));
