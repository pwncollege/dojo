export const dynamic = "auto";

import { motion } from "framer-motion";
import {
	AlertCircle,
	BookOpen,
	Loader2,
	Star,
	Trophy,
	Users,
	Zap,
} from "lucide-react";
import Link from "next/link";
import ninjaImage from "@/assets/ninja.png";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Markdown } from "@/components/ui/markdown";
import { dojoService } from "@/services/dojo";
import { type Dojo, HomePageClient } from "./home-client";

async function getDojos(): Promise<Dojo[]> {
	try {
		// Use dojoService for server-side fetching (handles SSL properly)
		const response = await dojoService.getDojos();
		return response.dojos || [];
	} catch (error) {
		console.error("Failed to fetch dojos:", error);
		// Return empty array when API is unavailable
		return [];
	}
}

export default async function HomePage() {
	const dojos = await getDojos();

	return <HomePageClient dojos={dojos} />;
}
