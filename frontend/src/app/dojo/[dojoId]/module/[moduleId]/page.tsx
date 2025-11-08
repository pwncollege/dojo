import { dojoService } from "@/services/dojo";
import { ModulePageClient } from "./module-client";
import { notFound } from "next/navigation";

interface ModulePageProps {
  params: Promise<{
    dojoId: string;
    moduleId: string;
  }>;
}

async function getDojoWithModule(dojoId: string, moduleId: string) {
  try {
    const response = await dojoService.getDojoDetail(dojoId);
    const module = response.dojo.modules.find((m) => m.id === moduleId);

    if (!module) {
      return { dojo: response.dojo, module: null };
    }

    return { dojo: response.dojo, module };
  } catch (error) {}
}

export default async function ModulePage({ params }: ModulePageProps) {
  const resolvedParams = await params;
  const { dojoId, moduleId } = resolvedParams;

  if (!dojoId || !moduleId) {
    notFound();
  }

  console.log("---------------------- RESOURCES --------------------");
  const data = await getDojoWithModule(dojoId, moduleId);


  if (!data) {
    notFound();
  }

  if (!data.module) {
    notFound();
  }

  return (
    <ModulePageClient
      dojo={data.dojo}
      module={data.module}
      dojoId={dojoId}
      moduleId={moduleId}
    />
  );
}
