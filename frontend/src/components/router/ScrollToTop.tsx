"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

export function ScrollToTop() {
	const pathname = usePathname();

	useEffect(() => {
		// Scroll to top whenever the pathname changes
		window.scrollTo(0, 0);
	}, [pathname]);

	return null;
}
