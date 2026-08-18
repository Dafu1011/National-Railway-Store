import { Alert, Button, Modal, Typography } from "antd";
import { Clock3, Download } from "lucide-react";
import type { UpdateCheckResponse } from "./updateApi";

const { Paragraph, Text } = Typography;

type UpdateModalProps = {
  open: boolean;
  update: UpdateCheckResponse | null;
  appVersion: string;
  installing: boolean;
  onInstall: () => void;
  onLater: () => void;
};

export function UpdateModal({ open, update, appVersion, installing, onInstall, onLater }: UpdateModalProps) {
  const forceUpdate = Boolean(update?.force_update);

  return (
    <Modal
      open={open && Boolean(update?.has_update)}
      title="发现新版本"
      centered
      closable={!forceUpdate}
      maskClosable={!forceUpdate}
      onCancel={forceUpdate ? undefined : onLater}
      footer={[
        forceUpdate ? null : (
          <Button key="later" icon={<Clock3 size={16} />} onClick={onLater} disabled={installing}>
            下次再说
          </Button>
        ),
        <Button key="install" type="primary" icon={<Download size={16} />} loading={installing} onClick={onInstall}>
          立即更新
        </Button>,
      ]}
    >
      {update ? (
        <div className="update-modal-body">
          {forceUpdate ? <Alert type="warning" showIcon message="当前版本需要更新后继续使用。" /> : null}
          <div className="update-version-row">
            <div>
              <Text type="secondary">当前版本</Text>
              <strong>V{appVersion}</strong>
            </div>
            <div>
              <Text type="secondary">最新版本</Text>
              <strong>V{update.latest_version}</strong>
            </div>
          </div>
          <div className="update-notes">
            <Text type="secondary">本次更新内容</Text>
            {update.release_notes.length > 0 ? (
              <ul>
                {update.release_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : (
              <Paragraph>暂无更新说明。</Paragraph>
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
