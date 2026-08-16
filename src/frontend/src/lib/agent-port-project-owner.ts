export type ProjectOperationOwner = Readonly<{ project: string; generation: number }>;

export function captureProjectOperation(project: string, generation: number): ProjectOperationOwner {
  return { project, generation };
}

export function beginProjectRefresh(
  requestedProject: string,
  currentProject: string,
  currentGeneration: number,
): ProjectOperationOwner | null {
  return requestedProject === currentProject
    ? { project: requestedProject, generation: currentGeneration + 1 }
    : null;
}

export function ownsCurrentProject(
  owner: ProjectOperationOwner,
  currentProject: string,
  currentGeneration: number,
): boolean {
  return owner.project === currentProject && owner.generation === currentGeneration;
}
