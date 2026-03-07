"use client";

import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { Header } from "./Header";

export function ConditionalHeader() {
	const pathname = usePathname();

	// Check if we're in a workspace page or auth page
	const isWorkspacePage = pathname.includes("/workspace/");
	const isAuthPage =
		pathname.startsWith("/login") ||
		pathname.startsWith("/register") ||
		pathname.startsWith("/forgot-password");

	return <>{!isWorkspacePage && !isAuthPage && <Header />}</>;
}
