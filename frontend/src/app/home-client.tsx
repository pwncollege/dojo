"use client";

import { motion } from "framer-motion";
import { useMemo } from "react";
import { DojoNinja } from "@/components/ui/dojo-ninja";
import { DojoGrid, NoDojosState } from "./dojo-grid";

export interface Dojo {
	id: string;
	name: string;
	description?: string;
	type: string;
	official: boolean;
	award?: {
		belt?: string;
		emoji?: string;
	};
	modules: number;
	challenges: number;
	active_hackers: number;
}

interface HomePageClientProps {
	dojos: Dojo[];
}

// Belt order for sorting
const BELT_ORDER = [
	"white",
	"orange",
	"yellow",
	"green",
	"purple",
	"blue",
	"brown",
	"red",
	"black",
];

export interface SectionInfo {
	title: string;
	subtitle: string;
	description: React.ReactNode;
	footer?: React.ReactNode;
}

// Section layout of the front page of pwn.college
const DOJO_SECTIONS = {
	welcome: {
		title: "Getting Started",
		subtitle: "Learn the Basics!",
		description: (
			<>
				These first few dojos are designed to help you Get Started with the
				platform. Start here before venturing onwards!
			</>
		),
		footer: (
			<>After completing the dojos above, dive into the Core Material below!</>
		),
	},
	topic: {
		title: "Core Material",
		subtitle: "Earn Your Belts!",
		description: (
			<>
				These dojos form the official pwn.college curriculum, taking you on a
				curated journey through the art of hacking. As you progress and build
				your skills, like in a martial art, you will earn{" "}
				<a href="belts">belts</a> for completing dojo after dojo. We won't stop
				you from jumping around if you want (and have the requisite skills), but
				you must earn belts sequentially.
			</>
		),
		footer: (
			<>
				After completing the dojos above, not only will you be added to the{" "}
				<a href="belts">belts</a> page, but{" "}
				<i>we will send you actual pwn.college-embroidered belts</i>! To get
				your belt, <a href="mailto:pwn@pwn.college">send us an email</a> from
				the email address associated with your pwn.college account. We’ll then
				get your belt over to you (eventually)! Note that, due to logistical
				challenges, we're currently only <i>shipping</i> belts to hackers after
				they earn their blue belt. Until then, we will belt you in person, at
				ASU or some security conference.
			</>
		),
	},
	public: {
		title: "Community Material",
		subtitle: "Earn Badges!",
		description: (
			<>
				No matter how much material we create, there is always more to learn!
				This section contains additional dojos created by the pwn.college
				community. Some are designed to be tackled after you complete the dojos
				above, whereas others are open to anyone interested in more specialized
				topics.
			</>
		),
	},
	course: {
		title: "The Courses",
		subtitle: "Earning Credit",
		description: (
			<>
				We leverage the above material to run a number of courses on this
				platform. For the most part, these courses import the above material,
				though some might introduce new concepts and challenges.
			</>
		),
	},
	member: {
		title: "Dojos You've Joined",
		subtitle: "Keep Hacking!",
		description: (
			<>
				These are the private dojos that have been shared with you. Keep
				hacking!
			</>
		),
		footer: (
			<>To join a private dojo, ask its sensei to send you an invite link!</>
		),
	},
	admin: {
		title: "Your Dojos",
		subtitle: "Challenge the World!",
		description: (
			<>
				You can create your own dojo, either hosting your own challenges or
				remixing existing material! Once created, a dojo can be shared with your
				friends or students (providing a private scoreboard and curated
				experience) or made public to the world to appear in the Community
				Material list above!
			</>
		),
		footer: (
			<>
				Want to add your dojo to the fray?
				<a href="/dojos/create">
					<b>Create it here</b>
				</a>
				!
			</>
		),
	},
} satisfies Record<string, SectionInfo>;

// Group all dojos by their `type` property
// The result will be an object where each key is a dojo type
// and the value is an array of Dojo objects of that type
const groupDojosByType = (dojos: Dojo[]) =>
	dojos.reduce<Record<string, Dojo[]>>((acc, dojo) => {
		if (!acc[dojo.type]) {
			acc[dojo.type] = [];
		}
		acc[dojo.type].push(dojo);
		return acc;
	}, {});

export function HomePageClient({ dojos }: HomePageClientProps) {
	// Memoize computed values to prevent infinite re-renders
	const { sectionedDojos } = useMemo<{
		sectionedDojos: Record<string, Dojo[]>;
	}>(
		() => ({
			sectionedDojos: groupDojosByType(dojos),
		}),
		[dojos],
	);

	return (
		<motion.div
			className="min-h-screen bg-background text-foreground"
			initial={{ opacity: 0, y: 20 }}
			animate={{ opacity: 1, y: 0 }}
			exit={{ opacity: 0, y: -20 }}
			transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
		>
			{/* Hero Section with Full Width Background */}
			<div className="relative">
				<div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-20 lg:py-24">
					<div className="relative grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
						<div className="max-w-4xl relative z-10">
							{/* Subtle backdrop with gradient for text visibility */}
							<div
								className="absolute -inset-8 bg-gradient-to-br from-background via-background/90 to-background/60 rounded-3xl"
								style={{ zIndex: -1 }}
							/>

							<div className="relative z-10">
								<h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 bg-gradient-to-r from-foreground to-muted-foreground bg-clip-text text-transparent">
									Learn to Hack!
								</h1>
								<p className="text-muted-foreground text-lg sm:text-xl lg:text-2xl leading-relaxed mb-8 max-w-3xl">
									The material is split into a number of "dojos", with each dojo
									typically covering a high-level topic. The material is
									designed to be tackled in order.
								</p>
								<div className="text-sm sm:text-base text-muted-foreground">
									{dojos.length} {dojos.length === 1 ? "dojo" : "dojos"}{" "}
									available
								</div>
							</div>
						</div>
						<div className="flex justify-center lg:justify-end">
							<motion.div
								initial={{ opacity: 0, scale: 0.8, y: 20 }}
								animate={{
									opacity: 1,
									scale: 1,
									y: 0,
								}}
								transition={{
									duration: 0.8,
									ease: [0.25, 0.46, 0.45, 0.94],
								}}
								className="relative"
							>
								<motion.div
									animate={{
										y: [0, -15, 0],
										rotateZ: [0, 1, -1, 0],
									}}
									transition={{
										duration: 6,
										repeat: Infinity,
										ease: "easeInOut",
									}}
								>
									<DojoNinja
										className="w-[400px] h-[400px] sm:w-80 sm:h-80 lg:w-[600px] lg:h-[600px] drop-shadow-2xl"
										width={600}
										height={600}
										priority
									/>
								</motion.div>
							</motion.div>
						</div>
					</div>
				</div>
			</div>

			<motion.div>
				<div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
					{Object.entries(DOJO_SECTIONS).map(([sectionType, sectionInfo]) => (
						<DojoGrid
							key={sectionType}
							dojos={sectionedDojos[sectionType] || []}
							sectionInfo={sectionInfo}
						/>
					))}
					{dojos.length === 0 && <NoDojosState />}
				</div>
			</motion.div>
		</motion.div>
	);
}
