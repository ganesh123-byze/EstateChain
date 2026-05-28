export type RoleKey = "investor" | "property_owner" | "tenant";

export type QuickAction = {
  id: string;
  label: string;
  prompt: string;
  icon: string;
};

const INVESTOR_ACTIONS: QuickAction[] = [
  {
    id: "investor.marketplace",
    label: "Browse marketplace",
    prompt: "Take me to the marketplace and summarize the properties available for sale.",
    icon: "Store",
  },
  {
    id: "investor.portfolio",
    label: "My portfolio",
    prompt: "Show me my investment portfolio with current valuations.",
    icon: "PieChart",
  },
  {
    id: "investor.yield",
    label: "Yield & returns",
    prompt: "What is my current yield and projected returns?",
    icon: "TrendingUp",
  },
  {
    id: "investor.transactions",
    label: "Recent transactions",
    prompt: "Show me my recent transactions.",
    icon: "Receipt",
  },
];

const PROPERTY_OWNER_ACTIONS: QuickAction[] = [
  {
    id: "owner.create",
    label: "List new property",
    prompt: "Help me list a new property for tokenization.",
    icon: "Plus",
  },
  {
    id: "owner.analytics",
    label: "View analytics",
    prompt: "Show me analytics across my properties.",
    icon: "BarChart3",
  },
  {
    id: "owner.rent",
    label: "Rent collection",
    prompt: "Show pending rent collections and overdue tenants.",
    icon: "Wallet",
  },
  {
    id: "owner.investors",
    label: "My investors",
    prompt: "Show me the investors holding shares of my properties.",
    icon: "Users",
  },
];

const TENANT_ACTIONS: QuickAction[] = [
  {
    id: "tenant.pay",
    label: "Pay rent",
    prompt: "I want to pay this month's rent.",
    icon: "CreditCard",
  },
  {
    id: "tenant.rental",
    label: "My rental",
    prompt: "Show me my current rental details and lease.",
    icon: "Home",
  },
  {
    id: "tenant.history",
    label: "Payment history",
    prompt: "Show my rent payment history.",
    icon: "Clock",
  },
  {
    id: "tenant.transactions",
    label: "Transactions",
    prompt: "Show me all my recent transactions.",
    icon: "Receipt",
  },
];

const ROLE_ACTIONS: Record<RoleKey, QuickAction[]> = {
  investor: INVESTOR_ACTIONS,
  property_owner: PROPERTY_OWNER_ACTIONS,
  tenant: TENANT_ACTIONS,
};

export function getRoleFromPath(pathname: string | null | undefined): RoleKey | null {
  if (!pathname) return null;
  if (pathname.startsWith("/investor")) return "investor";
  if (pathname.startsWith("/property_owner")) return "property_owner";
  if (pathname.startsWith("/tenant")) return "tenant";
  return null;
}

export function getQuickActions(role: RoleKey | null): QuickAction[] {
  if (!role) return [];
  return ROLE_ACTIONS[role] ?? [];
}

export function getRoleLabel(role: RoleKey | null): string {
  if (role === "investor") return "Investor";
  if (role === "property_owner") return "Property Owner";
  if (role === "tenant") return "Tenant";
  return "Guest";
}
