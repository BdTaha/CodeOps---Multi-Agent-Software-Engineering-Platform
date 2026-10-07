import { createContext } from 'react';
import type { Workbench } from './useWorkbench';
export const WorkbenchContext = createContext<Workbench | null>(null);
