pragma ComponentBehavior: Bound

import QtQuick
import QtQuick as QQ
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    required property var backend
    property int categoryIndex: 0
    onCategoryIndexChanged: {
        erpPasswordField.revealPassword = false
        erpPasswordField.inputItem.focus = false
        page.forceActiveFocus()
    }
    onVisibleChanged: {
        if (!visible) {
            erpPasswordField.revealPassword = false
            erpPasswordField.inputItem.focus = false
            page.forceActiveFocus()
        }
    }

    readonly property color titleColor: "#1d2939"
    readonly property color bodyColor: "#344054"
    readonly property color secondaryColor: "#667085"
    readonly property color borderColor: "#d9e2ec"
    readonly property color blue: "#1677ff"

    FolderDialog {
        id: settingsOutputDialog
        title: "选择默认保存位置"
        currentFolder: appBackend.downloadsFolderUrl
        onAccepted: appBackend.setOutputFolder(selectedFolder)
    }

    component SectionTitle: Column {
        property string title: ""
        property string description: ""
        spacing: 6
        Text {
            text: parent.title
            color: page.titleColor
            font.pixelSize: 21
            font.weight: Font.DemiBold
        }
        Text {
            visible: parent.description.length > 0
            text: parent.description
            color: page.secondaryColor
            font.pixelSize: 13
        }
    }

    component FieldLabel: Text {
        color: page.bodyColor
        font.pixelSize: 14
        font.weight: Font.Medium
    }

    component SettingsInput: Rectangle {
        id: field
        property alias text: input.text
        property alias placeholderText: placeholder.text
        property bool passwordMode: false
        property bool revealPassword: false
        property alias inputItem: input
        signal editingStarted()

        implicitHeight: 44
        radius: 7
        color: "#ffffff"
        border.width: input.activeFocus ? 2 : 1
        border.color: input.activeFocus ? page.blue : page.borderColor
        clip: true

        Text {
            id: placeholder
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            visible: input.text.length === 0 && !input.activeFocus
            color: "#98a2b3"
            font.pixelSize: 14
        }
        QQ.TextInput {
            id: input
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: field.passwordMode ? 64 : 14
            verticalAlignment: QQ.TextInput.AlignVCenter
            activeFocusOnTab: true
            selectByMouse: true
            color: page.titleColor
            selectionColor: "#cde2ff"
            selectedTextColor: page.titleColor
            font.pixelSize: 15
            echoMode: field.passwordMode && !field.revealPassword
                ? TextInput.Password
                : TextInput.Normal
            onActiveFocusChanged: {
                if (activeFocus)
                    field.editingStarted()
            }
        }
        Text {
            anchors.right: parent.right
            anchors.rightMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            visible: field.passwordMode && input.text.length > 0
            text: field.revealPassword ? "隐藏" : "显示"
            color: page.blue
            font.pixelSize: 12
            MouseArea {
                anchors.fill: parent
                anchors.margins: -8
                cursorShape: Qt.PointingHandCursor
                onClicked: field.revealPassword = !field.revealPassword
            }
        }
    }

    component SettingRow: Rectangle {
        default property alias content: rowContent.data
        property string title: ""
        property string description: ""
        implicitHeight: 78
        radius: 8
        color: "#ffffff"
        border.color: page.borderColor

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: 18
            Column {
                Layout.fillWidth: true
                spacing: 5
                Text {
                    text: parent.parent.parent.title
                    color: page.bodyColor
                    font.pixelSize: 15
                    font.weight: Font.Medium
                }
                Text {
                    visible: parent.parent.parent.description.length > 0
                    text: parent.parent.parent.description
                    color: page.secondaryColor
                    font.pixelSize: 12
                }
            }
            Row {
                id: rowContent
                Layout.alignment: Qt.AlignVCenter
                spacing: 10
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 105
            color: "#f9fbfd"
            border.color: "#d6dde7"
            Column {
                anchors.left: parent.left
                anchors.leftMargin: 32
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Text {
                    text: "系统设置"
                    color: page.titleColor
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    text: "管理账号连接、下载规则与自动化参数"
                    color: page.secondaryColor
                    font.pixelSize: 14
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 24
            Layout.topMargin: 20
            radius: 11
            color: "#ffffff"
            border.color: "#d5dee9"

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    Layout.preferredWidth: 242
                    Layout.fillHeight: true
                    color: "#f7f9fc"
                    radius: 11

                    Rectangle {
                        anchors.right: parent.right
                        width: 1
                        height: parent.height
                        color: "#dfe6ee"
                    }

                    Column {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 7
                        Text {
                            width: parent.width
                            height: 34
                            verticalAlignment: Text.AlignVCenter
                            text: "设置分类"
                            color: "#8a94a3"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Repeater {
                            model: [
                                "账户与连接",
                                "下载与任务",
                                "自动化设置",
                                "系统维护",
                                "关于软件"
                            ]
                            delegate: Rectangle {
                                required property string modelData
                                required property int index
                                width: parent.width
                                height: 48
                                radius: 7
                                color: page.categoryIndex === index
                                    ? "#e8f2ff"
                                    : navMouse.containsMouse ? "#eef3f8" : "transparent"
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 3
                                    height: page.categoryIndex === parent.index ? 27 : 0
                                    radius: 2
                                    color: page.blue
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 17
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: parent.modelData
                                    color: page.categoryIndex === parent.index
                                        ? page.blue : page.bodyColor
                                    font.pixelSize: 14
                                    font.weight: page.categoryIndex === parent.index
                                        ? Font.DemiBold : Font.Normal
                                }
                                MouseArea {
                                    id: navMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.categoryIndex = parent.index
                                }
                            }
                        }
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: page.categoryIndex

                    // 账户与连接
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 30
                            spacing: 18

                            SectionTitle {
                                title: "ERP 账号"
                                description: "用于静默查询申请和上传附件"
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 250
                                radius: 9
                                color: "#fbfcfe"
                                border.color: page.borderColor

                                GridLayout {
                                    anchors.fill: parent
                                    anchors.margins: 22
                                    columns: 2
                                    columnSpacing: 20
                                    rowSpacing: 10

                                    FieldLabel { text: "用户名" }
                                    FieldLabel { text: "密码" }
                                    SettingsInput {
                                        id: erpUsernameField
                                        Layout.fillWidth: true
                                        text: appBackend.erpUsername
                                        placeholderText: "请输入 ERP 用户名"
                                    }
                                    SettingsInput {
                                        id: erpPasswordField
                                        Layout.fillWidth: true
                                        passwordMode: true
                                        placeholderText: appBackend.erpPasswordStored
                                            ? "••••••••  已安全保存"
                                            : "请输入 ERP 密码"
                                        onEditingStarted: {
                                            if (text.length === 0 && appBackend.erpPasswordStored)
                                                text = appBackend.loadSavedErpPassword(
                                                    erpUsernameField.text
                                                )
                                        }
                                    }

                                    Text {
                                        Layout.columnSpan: 2
                                        Layout.fillWidth: true
                                        text: Qt.platform.os === "windows"
                                            ? "密码已加密保存在 Windows 凭据管理器；点击密码框可输入新密码。"
                                            : "密码已加密保存在 macOS 钥匙串；点击密码框可输入新密码。"
                                        color: page.secondaryColor
                                        font.pixelSize: 12
                                    }

                                    RowLayout {
                                        Layout.columnSpan: 2
                                        Layout.fillWidth: true
                                        Layout.topMargin: 8
                                        spacing: 10
                                        Rectangle {
                                            width: 9
                                            height: 9
                                            radius: 5
                                            color: appBackend.erpConnectionBusy
                                                ? "#f5a623"
                                                : appBackend.erpConnectionSuccess
                                                    ? "#12a150" : "#98a2b3"
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: appBackend.erpConnectionStatus
                                            color: appBackend.erpConnectionSuccess
                                                ? "#12834a" : page.bodyColor
                                            font.pixelSize: 13
                                        }
                                        AppButton {
                                            text: "测试连接"
                                            enabled: !appBackend.erpConnectionBusy
                                            onClicked: appBackend.testErpConnection(
                                                erpUsernameField.text,
                                                erpPasswordField.text
                                            )
                                        }
                                        AppButton {
                                            text: "保存账号"
                                            primary: true
                                            enabled: !appBackend.erpConnectionBusy
                                            onClicked: {
                                                appBackend.saveErpAccount(
                                                    erpUsernameField.text,
                                                    erpPasswordField.text
                                                )
                                            }
                                        }
                                    }
                                }
                            }

                            Text {
                                text: "登录状态"
                                color: page.titleColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "清除 ERP 登录状态"
                                description: "账号密码不会被删除，下次操作时将重新登录"
                                AppButton {
                                    text: "清除"
                                    onClicked: appBackend.clearErpLoginState()
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // 下载与任务
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 30
                            spacing: 16
                            SectionTitle {
                                title: "下载与任务"
                                description: "设置默认保存位置和权益单生成规则"
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "默认保存位置"
                                description: appBackend.outputPath
                                AppButton {
                                    text: "更改"
                                    onClicked: settingsOutputDialog.open()
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "默认导出方式"
                                description: "导入 Excel 后默认使用的生成方式"
                                AppButton {
                                    text: "每人一份"
                                    primary: appBackend.exportMode === "individual"
                                    onClicked: appBackend.setExportMode("individual")
                                }
                                AppButton {
                                    text: "相同条件合并"
                                    primary: appBackend.exportMode === "batch"
                                    onClicked: appBackend.setExportMode("batch")
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "单批最多人数"
                                description: "相同条件合并时，每份 PDF 最多包含 1–100 人"
                                BatchSizeControl {
                                    value: appBackend.batchSize
                                    onValueEdited: function(newValue) {
                                        appBackend.setBatchSize(newValue)
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 140
                                radius: 8
                                color: "#fbfcfe"
                                border.color: page.borderColor
                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 12
                                    SettingsToggle {
                                        width: parent.width
                                        checked: appBackend.openOutputFolderAfterRun
                                        text: "任务完成后打开结果文件夹"
                                        onToggled: function(value) {
                                            appBackend.setOpenOutputFolderAfterRun(value)
                                        }
                                    }
                                    SettingsToggle {
                                        width: parent.width
                                        checked: appBackend.uploadToErp
                                        text: "下载完成后自动上传至 ERP"
                                        description: "按 Excel 中的任务编号匹配申请并上传 PDF"
                                        onToggled: function(value) {
                                            appBackend.setUploadToErp(value)
                                        }
                                    }
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // 自动化设置
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 30
                            spacing: 16
                            SectionTitle {
                                title: "自动化设置"
                                description: "根据网络和页面响应速度调整操作节奏"
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "执行节奏"
                                description: "稳定模式会在页面操作之间保留更长间隔"
                                AppButton {
                                    text: "快速"
                                    primary: appBackend.executionSpeed === "fast"
                                    onClicked: appBackend.setExecutionSpeed("fast")
                                }
                                AppButton {
                                    text: "标准"
                                    primary: appBackend.executionSpeed === "standard"
                                    onClicked: appBackend.setExecutionSpeed("standard")
                                }
                                AppButton {
                                    text: "稳定"
                                    primary: appBackend.executionSpeed === "stable"
                                    onClicked: appBackend.setExecutionSpeed("stable")
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "无结果确认时间"
                                description: "查询结果为空时，用于排除页面仍在加载"
                                BatchSizeControl {
                                    from: 3
                                    to: 60
                                    unit: "秒"
                                    value: appBackend.noResultConfirmSeconds
                                    onValueEdited: function(newValue) {
                                        appBackend.setNoResultConfirmSeconds(newValue)
                                    }
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "预览加载后的等待时间"
                                description: "正文加载完成后，再等待指定时间触发下载"
                                BatchSizeControl {
                                    from: 0
                                    to: 5000
                                    unit: "毫秒"
                                    value: appBackend.previewDownloadDelayMs
                                    onValueEdited: function(newValue) {
                                        appBackend.setPreviewDownloadDelayMs(newValue)
                                    }
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "下载超时时间"
                                description: "超过该时间仍未捕获文件时记录为下载失败"
                                BatchSizeControl {
                                    from: 5
                                    to: 180
                                    unit: "秒"
                                    value: appBackend.downloadTimeoutSeconds
                                    onValueEdited: function(newValue) {
                                        appBackend.setDownloadTimeoutSeconds(newValue)
                                    }
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // 系统维护
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 30
                            spacing: 16
                            SectionTitle {
                                title: "系统维护"
                                description: "查看运行日志并清理可重新生成的临时数据"
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "运行日志"
                                description: appBackend.logsPath
                                AppButton {
                                    text: "打开文件夹"
                                    onClicked: appBackend.openLogsFolder()
                                }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                title: "临时文件"
                                description: "清理失败截图和会话快照，不会删除已下载的权益单"
                                AppButton {
                                    text: "立即清理"
                                    onClicked: appBackend.clearTemporaryFiles()
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // 关于软件
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 30
                            spacing: 18
                            SectionTitle {
                                title: "关于软件"
                                description: "信息化人力桌面工作台"
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 180
                                radius: 9
                                color: "#fbfcfe"
                                border.color: page.borderColor
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 24
                                    spacing: 20
                                    Rectangle {
                                        width: 64
                                        height: 64
                                        radius: 13
                                        color: page.blue
                                        Image {
                                            anchors.centerIn: parent
                                            width: 38
                                            height: 38
                                            source: "../assets/app.svg"
                                        }
                                    }
                                    Column {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Text {
                                            text: "信息化人力工作台"
                                            color: page.titleColor
                                            font.pixelSize: 20
                                            font.weight: Font.Bold
                                        }
                                        Text {
                                            text: "版本 " + appBackend.appVersion
                                            color: page.secondaryColor
                                            font.pixelSize: 13
                                        }
                                        Text {
                                            text: "用于单位权益单获取与 ERP 附件上传。"
                                            color: page.bodyColor
                                            font.pixelSize: 14
                                        }
                                    }
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: appBackend
        function onErpAccountChanged() {
            erpPasswordField.revealPassword = false
            erpPasswordField.inputItem.focus = false
            page.forceActiveFocus()
        }
    }
}
