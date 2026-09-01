import 'server-only';
import fs from 'node:fs';
import path from 'node:path';
import type {Locale} from '../content/i18n';

const contentRoot=path.join(process.cwd(),'content','whitepapers');
const humanFiles:Record<Locale,string>={'zh-TW':'growthmap-user-whitepaper.zh-TW.md','zh-CN':'growthmap-user-whitepaper.zh-CN.md',en:'growthmap-user-whitepaper.en.md'};

export function readHumanWhitepaper(locale:Locale){return fs.readFileSync(path.join(contentRoot,humanFiles[locale]),'utf8')}
export function readAgentWhitepaper(){return fs.readFileSync(path.join(contentRoot,'growthmap-agent-llm-onboarding.md'),'utf8')}
