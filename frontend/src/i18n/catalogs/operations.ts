/** Runtime, task and history interface messages, assembled without silent overrides. */
import { combineCatalogs } from '../catalogMerge';
import { jobs } from './jobs';
import { environment } from './environment';
import { llm } from './llm';
import { history } from './history';

export const operations = combineCatalogs(jobs, environment, llm, history);
