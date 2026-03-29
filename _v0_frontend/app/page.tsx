import { FlowmindIDE } from "@agentswarm/shared-swarm/flowmind";

export default function Page() {
  return (
    <FlowmindIDE 
      config={{
        title: "FLOWMIND FACTORY IDE",
        initialMessage: "Send a prompt to test the Flowmind simulator."
      }} 
    />
  );
}
