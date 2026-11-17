import {batches,inspections,reviews,offline} from '../api/business.js';
export const state={user:null,batches:[],inspections:[],reviews:[],packages:[],selected:null,pkg:null,pendingUpload:null};
export async function refresh(){[state.batches,state.inspections,state.reviews,state.packages]=await Promise.all([batches.list(),inspections.list(),reviews.list(),offline.list()]);if(state.selected)state.selected=await reviews.get(state.selected.id);if(state.pkg)state.pkg=await offline.get(state.pkg.id);}
