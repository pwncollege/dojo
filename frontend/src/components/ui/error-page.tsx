"use client";

import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Home, RefreshCw, ArrowLeft } from "lucide-react";
import { motion } from "framer-motion";
import ninjaErrorImage from "@/assets/ninja-error.png";

interface ErrorPageProps {
  title?: string;
  description?: string;
  statusCode?: number;
  showRefresh?: boolean;
  showBack?: boolean;
  showHome?: boolean;
}

export function ErrorPage({
  title = "Something went wrong",
  description = "We encountered an unexpected error. Please try again.",
  statusCode = 500,
  showRefresh = true,
  showBack = false,
  showHome = true,
}: ErrorPageProps) {
  const handleRefresh = () => {
    window.location.reload();
  };

  const handleBack = () => {
    window.history.back();
  };

  // Get status-based message
  const getStatusMessage = (code: number) => {
    switch (code) {
      case 404:
        return "Oops! I couldn't find that in the dojo";
      case 403:
        return "Access denied, young grasshopper";
      case 500:
        return "The dojo servers are taking a break";
      case 503:
        return "Dojo maintenance in progress";
      default:
        return "Something went wrong in the dojo";
    }
  };

  const statusMessage = getStatusMessage(statusCode);

  return (
    <div className="flex items-center h-[calc(100vh-100px)]  px-24">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.4 }}
        className="max-w-2xl mx-auto text-center space-y-4"
      >
        <div className="space-y-4">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-foreground">
            {statusMessage}
          </h1>
          <p className="text-lg text-muted-foreground max-w-lg mx-auto">
            {description}
          </p>
        </div>

        {/* Action Buttons */}
        {(showBack || showRefresh || showHome) && (
              <div className="flex flex-col justify-center mt-8 sm:flex-row gap-3">
                {showBack && (
                  <Button
                    variant="outline"
                    onClick={handleBack}
                    className="flex items-center gap-2"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Go Back
                  </Button>
                )}

                {showRefresh && (
                  <Button
                    variant="outline"
                    onClick={handleRefresh}
                    className="flex items-center gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Try Again
                  </Button>
                )}

                {showHome && (
                  <Button asChild className="flex items-center gap-2">
                    <Link href="/">
                      <Home className="h-4 w-4" />
                      Go Home
                    </Link>
                  </Button>
                )}
              </div>
        )}
      </motion.div>
    </div>
  );
}
